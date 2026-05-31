"""Compile an SOP (markdown/checklist/policy text) into a CompiledWorkflow.

Two paths:

* **LLM-driven (optional):** if a provider/API key is configured, an LLM can
  produce the workflow JSON, schema-constrained. This is a hook -- it falls back
  silently when no key/provider is available.
* **Local fallback (default, no keys):** a deterministic parser turns markdown
  headings and checklist/bullet items into steps, inferring modality, evidence,
  tools, human-review points, decisions, and validation rules from inline tags
  and keywords.

Authors can guide the local compiler with optional inline tags inside a step
line, e.g.::

    - Capture the front bumper [vision] [evidence: front_bumper] [produces: front]
    - Look up the order in the CRM [tool: crm_lookup]
    - Send the resolution to the customer [review: customer_response]
    - If damage_found then route to senior review
      [decision: damage_found -> escalate_step | close_step]

Tags are optional; without them the compiler infers from keywords.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core.sop_compiler.workflow import (
    CompiledWorkflow,
    DecisionPoint,
    HumanReviewPoint,
    ValidationRule,
    WorkflowStep,
)

# --- keyword inference tables -------------------------------------------------

_VISION_KW = (
    "photo", "photograph", "capture", "image", "picture", "inspect", "look",
    "visually", "scan", "see", "camera", "snapshot",
)
_VOICE_KW = (
    "ask", "confirm with", "interview", "verbally", "say", "speak", "record "
    "answer", "narrate", "tell the", "question the",
)
_TOOL_KW = (
    "look up", "lookup", "query", "api", "database", "ticket", "fetch",
    "check status", "retrieve", "search", "crm", "record in", "create a ticket",
    "update the", "call the", "system", "knowledge base", "run the",
)

_REVIEW_TRIGGERS = {
    "final_submit": ("submit", "finalize", "final report", "finalise", "sign off"),
    "doc_rejection": ("reject", "rejection", "decline the document"),
    "valuation_change": ("valuation", "reduce price", "price change", "deduction"),
    "customer_response": (
        "send the customer", "customer response", "reply to the customer",
        "send the resolution", "respond to the customer", "send response",
    ),
    "compliance_fail": ("compliance fail", "mark non-compliant", "compliance failure"),
}

_TAG_RE = re.compile(r"\[([a-zA-Z_]+)\s*:?\s*([^\]]*)\]")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.*\S)\s*$")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*\S)\s*$")


def _slug(text: str, used: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48] or "step"
    candidate = base
    i = 2
    while candidate in used:
        candidate = f"{base}_{i}"
        i += 1
    used.add(candidate)
    return candidate


def _parse_tags(text: str) -> Tuple[str, Dict[str, str]]:
    """Strip inline ``[key: value]`` tags, returning (clean_text, tags)."""
    tags: Dict[str, str] = {}
    for m in _TAG_RE.finditer(text):
        key = m.group(1).strip().lower()
        val = (m.group(2) or "").strip()
        tags[key] = val
    clean = _TAG_RE.sub("", text).strip()
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean, tags


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in re.split(r"[;,]", value) if v.strip()]


def _infer_modality(text: str, tags: Dict[str, str]) -> str:
    for m in ("vision", "voice", "tool", "reason", "none"):
        if m in tags:
            return m
    if "tool" in tags:
        return "tool"
    low = text.lower()
    if any(k in low for k in _TOOL_KW):
        return "tool"
    if any(k in low for k in _VISION_KW):
        return "vision"
    if any(k in low for k in _VOICE_KW):
        return "voice"
    return "reason"


def _infer_review_trigger(text: str) -> Optional[str]:
    low = text.lower()
    for trigger, kws in _REVIEW_TRIGGERS.items():
        if any(k in low for k in kws):
            return trigger
    return None


def _build_step(
    text: str, used_ids: set
) -> Tuple[WorkflowStep, Optional[HumanReviewPoint], List[DecisionPoint], List[ValidationRule]]:
    clean, tags = _parse_tags(text)
    step_id = _slug(clean, used_ids)
    modality = _infer_modality(clean, tags)

    tools_needed: List[str] = []
    if "tool" in tags and tags["tool"]:
        tools_needed = _split_csv(tags["tool"])

    required_evidence: List[str] = []
    if "evidence" in tags and tags["evidence"]:
        required_evidence = _split_csv(tags["evidence"])
    elif modality == "vision":
        required_evidence = [f"{step_id}_photo"]

    produces: List[str] = []
    if "produces" in tags and tags["produces"]:
        produces = _split_csv(tags["produces"])
    else:
        produces = [step_id]

    drilldowns: List[str] = []
    if "ask" in tags and tags["ask"]:
        drilldowns = _split_csv(tags["ask"])

    min_conf = 0.4
    if "min_confidence" in tags and tags["min_confidence"]:
        try:
            min_conf = float(tags["min_confidence"])
        except ValueError:
            pass

    review_point: Optional[HumanReviewPoint] = None
    review_trigger = tags.get("review") or _infer_review_trigger(clean)
    review_id: Optional[str] = None
    if review_trigger:
        review_id = f"hrp_{step_id}"
        review_point = HumanReviewPoint(
            id=review_id,
            step_id=step_id,
            trigger=review_trigger,
            description=clean,
            risk="high" if review_trigger in ("final_submit", "compliance_fail")
            else "medium",
        )

    decisions: List[DecisionPoint] = []
    if "decision" in tags and tags["decision"]:
        decisions.append(_parse_decision(step_id, tags["decision"]))

    rules: List[ValidationRule] = []
    if "validate" in tags and tags["validate"]:
        rules.append(
            ValidationRule(
                id=f"rule_{step_id}",
                applies_to=step_id,
                expression=tags["validate"],
                message=f"Validation failed for step '{step_id}'.",
                severity="error",
            )
        )

    step = WorkflowStep(
        id=step_id,
        title=clean[:80],
        description=clean,
        modality=modality,
        instruction=clean,
        required_evidence=required_evidence,
        tools_needed=tools_needed,
        produces=produces,
        human_review_point=review_id,
        summary_template=tags.get("summary", ""),
        drilldown_questions=drilldowns,
        min_confidence=min_conf,
    )
    return step, review_point, decisions, rules


def _parse_decision(step_id: str, spec: str) -> DecisionPoint:
    """Parse ``<condition> -> <on_true> | <on_false>``."""
    condition, _, rest = spec.partition("->")
    on_true, _, on_false = rest.partition("|")
    return DecisionPoint(
        id=f"dp_{step_id}",
        step_id=step_id,
        question=condition.strip(),
        condition=condition.strip(),
        on_true=on_true.strip(),
        on_false=on_false.strip(),
    )


def _parse_markdown(sop_text: str) -> Tuple[str, List[str]]:
    """Return (goal, list of raw step texts) from markdown/checklist text."""
    goal = "complete_sop"
    raw_steps: List[str] = []
    pending_heading: Optional[str] = None
    heading_had_items = False
    first_h1_seen = False

    for line in sop_text.splitlines():
        if not line.strip():
            continue
        h = _HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            title = h.group(2).strip()
            if level == 1 and not first_h1_seen:
                goal = title
                first_h1_seen = True
                pending_heading = None
                heading_had_items = False
                continue
            # A previous sub-heading with no bullets becomes its own step.
            if pending_heading is not None and not heading_had_items:
                raw_steps.append(pending_heading)
            pending_heading = title
            heading_had_items = False
            continue
        m = _LIST_RE.match(line)
        if m:
            raw_steps.append(m.group(1).strip())
            heading_had_items = True
            continue
        # Plain prose lines under a heading are ignored as context.
    if pending_heading is not None and not heading_had_items:
        raw_steps.append(pending_heading)
    return goal, raw_steps


def compile_local(
    sop_text: str,
    *,
    sop_version: str = "v1",
    output_schema: Optional[Dict[str, Any]] = None,
) -> CompiledWorkflow:
    """Deterministic, no-API-key compilation path."""
    goal, raw_steps = _parse_markdown(sop_text)
    used_ids: set = set()
    steps: List[WorkflowStep] = []
    review_points: List[HumanReviewPoint] = []
    decisions: List[DecisionPoint] = []
    rules: List[ValidationRule] = []

    for raw in raw_steps:
        step, rp, dps, vrs = _build_step(raw, used_ids)
        steps.append(step)
        if rp:
            review_points.append(rp)
        decisions.extend(dps)
        rules.extend(vrs)

    required_evidence = sorted(
        {e for s in steps for e in s.required_evidence}
    )
    tools_needed = sorted({t for s in steps for t in s.tools_needed})

    schema = output_schema if output_schema else suggest_output_schema(steps, goal)

    return CompiledWorkflow(
        goal=re.sub(r"[^a-z0-9]+", "_", goal.lower()).strip("_") or "complete_sop",
        sop_version=sop_version,
        source="local-fallback",
        steps=steps,
        required_evidence=required_evidence,
        decision_points=decisions,
        tools_needed=tools_needed,
        validation_rules=rules,
        human_review_points=review_points,
        output_schema=schema,
    )


def suggest_output_schema(
    steps: List[WorkflowStep], goal: str = "complete_sop"
) -> Dict[str, Any]:
    """Propose a JSON-Schema-ish output from the compiled steps.

    Used when the author sets ``output_schema: suggest`` (or provides none). The
    suggestion is editable -- it is just a starting point keyed off each step's
    ``produces`` fields, plus a summary + completion fields.
    """
    properties: Dict[str, Any] = {
        "summary": {"type": "string", "description": "Overall result summary."},
        "completed": {"type": "boolean", "description": "All steps completed."},
    }
    for step in steps:
        for field in step.produces:
            properties.setdefault(
                field,
                {
                    "type": "object",
                    "description": f"Result of step '{step.title}'.",
                    "properties": {
                        "value": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            )
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{goal}_output",
        "type": "object",
        "properties": properties,
        "required": ["summary", "completed"],
    }


def _compile_with_llm(
    sop_text: str, config: Dict[str, Any]
) -> Optional[CompiledWorkflow]:
    """Optional LLM compilation hook.

    Returns ``None`` (triggering the local fallback) unless a provider and API
    key are both available. Kept dependency-light on purpose: we only attempt the
    call when explicitly enabled and configured, and any failure falls back.
    """
    if not config.get("use_llm"):
        return None
    api_key = os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"))
    if not api_key:
        return None
    try:  # pragma: no cover - exercised only with a real provider/key
        from core.sop_compiler.llm import compile_with_llm  # type: ignore

        return compile_with_llm(sop_text, config, api_key)
    except Exception:
        # Any provider/import/parse failure -> deterministic fallback.
        return None


def compile_sop(
    sop_text: str,
    *,
    sop_version: str = "v1",
    output_schema: Optional[Dict[str, Any]] = None,
    compiler_config: Optional[Dict[str, Any]] = None,
) -> CompiledWorkflow:
    """Compile an SOP into an executable workflow.

    Tries the (optional) LLM path first when configured/keyed, then always falls
    back to the deterministic local parser. ``output_schema=None`` means
    "suggest one".
    """
    config = compiler_config or {}
    llm_result = _compile_with_llm(sop_text, config)
    if llm_result is not None:
        if not llm_result.output_schema and output_schema:
            llm_result.output_schema = output_schema
        return llm_result
    return compile_local(
        sop_text, sop_version=sop_version, output_schema=output_schema
    )
