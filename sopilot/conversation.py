"""Generate guided conversation contracts from SOPilot manifests.

Voice/browser agents need the same shape across products: inspect journey state,
capture required media, record interview answers, submit for analysis, retry weak
evidence, then stop. This module derives that contract from an
``AgentManifest`` and allows product-specific tool-name overrides.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field

from sopilot.scaffold import AgentManifest, MediaRequirement


class RecordTopic(BaseModel):
    key: str
    label: str
    description: str = ""
    required: bool = True


class GuidedToolNames(BaseModel):
    state: str = "getSOPilotState"
    submit: str = "submitSOPilotRun"
    record_answer: str = "recordInterviewAnswer"
    capture_by_evidence: dict[str, str] = Field(default_factory=dict)


def build_guided_tool_names(
    manifest: AgentManifest,
    *,
    state_tool: str = "getSOPilotState",
    submit_tool: str = "submitSOPilotRun",
    record_answer_tool: str = "recordInterviewAnswer",
    capture_tool_overrides: Optional[Mapping[str, str]] = None,
) -> GuidedToolNames:
    capture_tool_overrides = capture_tool_overrides or {}
    capture_by_evidence: dict[str, str] = {}
    for req in manifest.media_requirements:
        if req.modality != "vision":
            continue
        evidence = req.evidence_refs[0] if req.evidence_refs else req.step_id
        capture_by_evidence[evidence] = capture_tool_overrides.get(
            evidence,
            f"capture{_pascal(evidence)}",
        )
    return GuidedToolNames(
        state=state_tool,
        submit=submit_tool,
        record_answer=record_answer_tool,
        capture_by_evidence=capture_by_evidence,
    )


def build_client_tool_summary(
    manifest: AgentManifest,
    names: GuidedToolNames,
) -> dict[str, str]:
    tools = {
        names.state: f"Returns the current {manifest.name} journey state and next step.",
        names.record_answer: "Records one interview answer before the agent asks the next question.",
        names.submit: f"Submits collected evidence for {manifest.name} analysis.",
    }
    for requirement in _vision_requirements(manifest):
        evidence = requirement.evidence_refs[0] if requirement.evidence_refs else requirement.step_id
        tools[names.capture_by_evidence[evidence]] = (
            f"Captures the current browser camera frame as {evidence}."
        )
    return tools


def build_client_tool_configs(
    manifest: AgentManifest,
    names: GuidedToolNames,
    *,
    record_topics: Optional[list[RecordTopic | Mapping[str, Any]]] = None,
    structured_properties: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    topics = _record_topics(manifest, record_topics)
    tools: list[dict[str, Any]] = [
        {
            "type": "client",
            "name": names.state,
            "description": f"Return the current {manifest.name} journey state, including collected evidence and next step.",
            "expects_response": True,
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    for requirement in _vision_requirements(manifest):
        evidence = requirement.evidence_refs[0] if requirement.evidence_refs else requirement.step_id
        tools.append(
            {
                "type": "client",
                "name": names.capture_by_evidence[evidence],
                "description": (
                    f"Capture the current browser camera frame as {evidence}. "
                    f"Call this only after asking the user for: {requirement.title}."
                ),
                "expects_response": True,
                "parameters": {"type": "object", "properties": {}},
            }
        )

    if _voice_requirement(manifest):
        tools.append(_record_answer_tool(names.record_answer, topics, structured_properties))

    tools.append(_submit_tool(manifest, names.submit))
    return tools


def build_guided_instructions(
    manifest: AgentManifest,
    names: GuidedToolNames,
    *,
    record_topics: Optional[list[RecordTopic | Mapping[str, Any]]] = None,
    domain_rules: str = "",
    failure_policy: str = "",
    final_policy: str = "",
) -> str:
    topics = _record_topics(manifest, record_topics)
    parts: list[str] = [
        f"Guide the user through the {manifest.name} journey in order.",
        f"Start by calling {names.state} when you need the current browser state.",
    ]
    for requirement in manifest.media_requirements:
        if requirement.modality == "vision":
            evidence = requirement.evidence_refs[0] if requirement.evidence_refs else requirement.step_id
            parts.append(
                f"Ask the user for this capture: {requirement.title}. "
                f"Then call {names.capture_by_evidence[evidence]} and wait for its result."
            )
        elif requirement.modality == "voice":
            questions = requirement.drilldown_questions or [requirement.title]
            parts.append(
                "After required captures, ask these interview questions sequentially, "
                "one at a time, and wait for each answer before continuing: "
                + " ".join(f"{index + 1}. {question}" for index, question in enumerate(questions))
            )
            if topics:
                labels = ", ".join(f"{topic.key} ({topic.label})" for topic in topics)
                parts.append(
                    f"Immediately after each answer, call {names.record_answer} with the matching topic. "
                    f"Accepted topics are: {labels}. Never use blank, guessed, placeholder, or dummy values."
                )
            else:
                parts.append(
                    f"Immediately after each answer, call {names.record_answer}. "
                    "Never use blank, guessed, placeholder, or dummy values."
                )
    transcript_field = _submit_transcript_field(manifest)
    parts.append(
        f"After collection is complete, call {names.submit} with {transcript_field} as a concise summary of the recorded answers."
    )
    retry_policy = build_retry_policy(manifest, names)
    if retry_policy:
        parts.append(retry_policy)
    for optional in (domain_rules, failure_policy, final_policy):
        if optional.strip():
            parts.append(optional.strip())
    return " ".join(parts)


def infer_record_topics(manifest: AgentManifest) -> list[RecordTopic]:
    """Build stable interview-topic enums from the manifest voice questions."""
    voice = _voice_requirement(manifest)
    if not voice:
        return []
    questions = voice.drilldown_questions or [voice.title]
    topics: list[RecordTopic] = []
    seen: set[str] = set()
    for index, question in enumerate(questions, start=1):
        label = _question_label(question)
        key = _topic_key(label) or f"topic_{index}"
        if key in seen:
            key = f"{key}_{index}"
        seen.add(key)
        topics.append(
            RecordTopic(
                key=key,
                label=label,
                description=question,
            )
        )
    return topics


def build_retry_policy(manifest: AgentManifest, names: GuidedToolNames) -> str:
    vision = _vision_requirements(manifest)
    voice = _voice_requirement(manifest)
    if not vision and not voice:
        return ""

    clauses: list[str] = [
        "If any client tool returns ok:false, missing_fields, low_confidence_fields, "
        "retry_media_fields, retry_photo_fields, failures, or next_steps, follow that "
        "tool response exactly and recover only the missing or weak evidence."
    ]
    if vision:
        retry_map = []
        for requirement in vision:
            evidence = requirement.evidence_refs[0] if requirement.evidence_refs else requirement.step_id
            retry_map.append(f"{evidence} -> {names.capture_by_evidence[evidence]}")
        clauses.append(
            "For media retries, preserve all successful captures and answers; ask only for "
            "the named capture again. Capture map: " + "; ".join(retry_map) + "."
        )
    if voice:
        clauses.append(
            "Do not re-ask interview answers that have already been recorded unless the "
            "tool response explicitly names an unanswered or invalid topic."
        )
    return " ".join(clauses)


def _record_answer_tool(
    name: str,
    topics: list[RecordTopic],
    structured_properties: Optional[dict[str, Any]],
) -> dict[str, Any]:
    topic_property: dict[str, Any] = {
        "type": "string",
        "description": "The single interview topic just answered by the user.",
    }
    if topics:
        topic_property["enum"] = [topic.key for topic in topics]
        topic_property["description"] = (
            "The single interview topic just answered by the user. "
            "Use one of the generated topic keys."
        )

    properties: dict[str, Any] = {
        "topic": topic_property,
        "answer": {
            "type": "string",
            "minLength": 1,
            "description": "The user's answer in their own words. Never invent or fill with dummy text.",
        },
    }
    if structured_properties is not None:
        properties["structured"] = {
            "type": "object",
            "additionalProperties": False,
            "description": "Optional normalized fields, only when the user explicitly provided them.",
            "properties": structured_properties,
        }
    return {
        "type": "client",
        "name": name,
        "description": "Record exactly one interview answer after asking the matching question.",
        "expects_response": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["topic", "answer"],
            "properties": properties,
        },
    }


def _record_topics(
    manifest: AgentManifest,
    topics: Optional[list[RecordTopic | Mapping[str, Any]]],
) -> list[RecordTopic]:
    if topics is None:
        return infer_record_topics(manifest)
    return [
        topic if isinstance(topic, RecordTopic) else RecordTopic.model_validate(topic)
        for topic in topics
    ]


def _submit_tool(manifest: AgentManifest, name: str) -> dict[str, Any]:
    transcript_field = _submit_transcript_field(manifest)
    voice = _voice_requirement(manifest)
    description = voice.title if voice else "the user's interview answers"
    return {
        "type": "client",
        "name": name,
        "description": f"Submit collected evidence and {description} for analysis.",
        "expects_response": True,
        "parameters": {
            "type": "object",
            "required": [transcript_field],
            "properties": {
                transcript_field: {
                    "type": "string",
                    "description": f"Concise transcript or summary of {description}.",
                }
            },
        },
    }


def _submit_transcript_field(manifest: AgentManifest) -> str:
    voice = _voice_requirement(manifest)
    if voice and voice.produces:
        return f"{voice.produces[0]}_transcript"
    return "interview_transcript"


def _vision_requirements(manifest: AgentManifest) -> list[MediaRequirement]:
    return [req for req in manifest.media_requirements if req.modality == "vision"]


def _voice_requirement(manifest: AgentManifest) -> Optional[MediaRequirement]:
    return next((req for req in manifest.media_requirements if req.modality == "voice"), None)


def _pascal(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+", value) if part)


def _topic_key(label: str) -> str:
    compact = re.sub(
        r"\b(what|which|where|when|why|how|is|are|the|a|an|your|you|does|do|get|like|and|or)\b",
        " ",
        label.lower(),
    )
    parts = re.findall(r"[a-z0-9]+", compact)
    return "_".join(parts[:6])


def _question_label(question: str) -> str:
    cleaned = question.strip().strip("?!.")
    cleaned = re.sub(r"^(what|which|where|when|why|how)\s+", "", cleaned, flags=re.I)
    return cleaned[:1].lower() + cleaned[1:] if cleaned else "interview topic"
