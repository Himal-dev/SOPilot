"""Evidence-grounded Plant Doctor report assembly.

The generic SOP runner can execute the workflow, but its local "reason" steps
are intentionally simple. This module turns the actual observations into a
domain report and refuses to fill diagnosis/care-plan fields when evidence is
missing or fixture-only.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sopilot.report_writer import (
    ReportPromptSpec,
    build_report_prompt_payload,
    write_openai_json_report,
)
from sopilot.report_view import (
    build_report_view,
    first_text,
    listify,
    primary_cause_from_diagnosis,
    recommendations_from_plan,
)
from sopilot.reporting import (
    ReportFieldSpec,
    build_report_readiness,
    report_field_specs_from_manifest,
)

REQUIRED_FIELDS = ("plant", "symptoms", "care_habits")
PLANT_FIELD_OVERRIDES = {
    "plant": {
        "label": "whole-plant photo",
        "missing_reason": "Missing reliable whole-plant photo evidence for plant identification.",
        "retry_instruction": "Retake the whole-plant photo.",
    },
    "symptoms": {
        "label": "close-up photo",
        "missing_reason": "Missing reliable close-up photo evidence for visible symptoms.",
        "retry_instruction": "Retake the close-up photo.",
    },
    "care_habits": {
        "label": "care-habits answer",
        "missing_reason": "Missing reliable care-habits answer evidence.",
        "retry_instruction": "Collect a spoken care-habits answer through the ElevenLabs agent.",
    },
}
FALLBACK_FIELD_SPECS = [
    ReportFieldSpec(
        name="plant",
        label="whole-plant photo",
        step_id="capture_the_whole_plant_in_frame",
        modality="vision",
        evidence_refs=["whole_plant_photo"],
        missing_reason=PLANT_FIELD_OVERRIDES["plant"]["missing_reason"],
        retry_instruction=PLANT_FIELD_OVERRIDES["plant"]["retry_instruction"],
    ),
    ReportFieldSpec(
        name="symptoms",
        label="close-up photo",
        step_id="capture_a_close_up_of_the_affected_leaves_or_ste",
        modality="vision",
        evidence_refs=["closeup_photo"],
        missing_reason=PLANT_FIELD_OVERRIDES["symptoms"]["missing_reason"],
        retry_instruction=PLANT_FIELD_OVERRIDES["symptoms"]["retry_instruction"],
    ),
    ReportFieldSpec(
        name="care_habits",
        label="care-habits answer",
        step_id="ask_the_gardener_about_care_habits_and_recent_ch",
        modality="voice",
        evidence_refs=["care_habits_audio"],
        missing_reason=PLANT_FIELD_OVERRIDES["care_habits"]["missing_reason"],
        retry_instruction=PLANT_FIELD_OVERRIDES["care_habits"]["retry_instruction"],
    ),
]
PLANT_REPORT_PROMPT = ReportPromptSpec(
    name="plant_doctor_report",
    expert_role=(
        "You are a senior plant-health expert: practical, specific, and evidence-bound. "
        "Think like an experienced horticulturist doing triage from photos plus care history."
    ),
    task=(
        "Use the whole-plant photo, close-up symptoms, care routine, and recent-change "
        "context to weigh the most likely cause against plausible alternatives. Explain "
        "the visible issue, root-cause logic, what to do today, how to adjust routine, "
        "what recovery signs to watch, and when the user should escalate."
    ),
    output_contract=(
        "{\"summary\": string, \"diagnosis\": {\"observed_issue\": string, "
        "\"root_cause_summary\": string, \"likely_causes\": [{\"cause\": string, "
        "\"basis\": string}], \"confidence\": number}, \"care_plan\": {"
        "\"immediate_actions\": [string], \"routine_adjustments\": [string], "
        "\"monitoring\": string, \"escalation\": string, \"actions\": [string], "
        "\"confidence\": number}}"
    ),
    evidence_policy=(
        "Distinguish observed evidence from inference. Weigh recent changes, watering, "
        "light, drainage/soil, and pests before choosing a root cause. Use only the "
        "provided observations and care-habits evidence. If uncertain, say exactly "
        "what is uncertain and lower confidence."
    ),
    style_rules=[
        "Avoid generic houseplant advice.",
        "Make the report specific and useful: explain what is wrong, why it is likely happening now, what to do today, how to change routine, what recovery signs to watch next, and when to escalate.",
        "Do not invent species, symptoms, habits, causes, or actions.",
        "Do not return diagnosis or care_plan as strings.",
        "Do not recommend pesticides, fertilizer, repotting, or drastic pruning unless the evidence supports it.",
    ],
    model_env="OPENAI_PLANT_DOCTOR_REPORT_MODEL",
    default_model="gpt-4o",
    max_tokens=1100,
)


def build_plant_care_report(
    run_data: Dict[str, Any],
    *,
    allow_demo_data: bool = False,
    report_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    manifest: Any = None,
) -> Dict[str, Any]:
    """Return a Plant Doctor report with no SOP-instruction placeholders."""
    risks = run_data.get("risks", []) or []

    readiness = build_report_readiness(
        run_data,
        _report_field_specs(manifest),
        allow_demo_data=allow_demo_data,
        demo_data_next_step="Set OPENAI_API_KEY and rerun with real vision analysis.",
    )
    fields = readiness.fields
    demo_used = readiness.demo_data_used

    report: Dict[str, Any] = {
        "summary": "",
        "completed": False,
        "_meta": {
            "status": run_data.get("status"),
            "source": "plant_doctor_report",
            "demo_data_used": demo_used,
            "risks": risks,
        },
        "_evidence": readiness.evidence,
    }
    for name, field in fields.items():
        if field is not None:
            report[name] = field

    if readiness.failures:
        return _incomplete_report(
            report,
            readiness.public_failures(),
            next_steps=readiness.next_steps,
        )

    model_report = _build_model_report(fields, report_fn=report_fn)
    if model_report is not None:
        try:
            diagnosis, care_plan = _extract_model_guidance(model_report, fields)
        except ValueError as exc:
            report["_meta"]["model_report_error"] = str(exc)
            report["_meta"]["model_report_model"] = model_report.get("model")
            return _incomplete_report(
                report,
                [{"field": "report_model", "reason": str(exc)}],
            )
    else:
        diagnosis, care_plan = _derive_care_guidance(fields)
    report["diagnosis"] = diagnosis
    report["care_plan"] = care_plan
    report_view = _care_report_view(
        fields,
        diagnosis,
        care_plan,
        run_status=run_data.get("status"),
        model_name=model_report.get("model", "local-evidence-rules")
        if model_report
        else "local-evidence-rules",
        demo_used=demo_used,
    )
    report["care_report"] = {
        **report_view,
        "status": "drafted" if run_data.get("status") == "interrupted" else "submitted",
        "basis": [
            "whole plant photo",
            "close-up photo",
            "gardener care-habits answer",
        ],
        "confidence": min(
            fields["plant"]["confidence"],
            fields["symptoms"]["confidence"],
            fields["care_habits"]["confidence"],
            diagnosis["confidence"],
        ),
        "warnings": ["Uses demo fixture data."] if demo_used else [],
        "model": model_report.get("model", "local-evidence-rules")
        if model_report
        else "local-evidence-rules",
    }
    report["completed"] = run_data.get("status") != "rejected"
    report["summary"] = _summary(fields, diagnosis)
    return report


def _build_model_report(
    fields: Dict[str, Dict[str, Any]],
    *,
    report_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    fn = report_fn or _default_report_fn
    if fn is None:
        return None
    payload = {
        **_model_report_fields(fields),
        "instruction": PLANT_REPORT_PROMPT.task,
    }
    try:
        data = fn(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _report_field_specs(manifest: Any = None) -> List[ReportFieldSpec]:
    if manifest is None:
        return list(FALLBACK_FIELD_SPECS)
    return report_field_specs_from_manifest(
        manifest,
        include_fields=REQUIRED_FIELDS,
        overrides=PLANT_FIELD_OVERRIDES,
    )


def _model_report_fields(fields: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        "plant": fields["plant"],
        "symptoms": fields["symptoms"],
        "care_habits": fields["care_habits"],
    }


def _incomplete_report(
    report: Dict[str, Any],
    failures: List[Dict[str, str]],
    *,
    next_steps: Optional[List[str]] = None,
) -> Dict[str, Any]:
    report["summary"] = "Plant Doctor could not produce a reliable care report."
    report["completed"] = False
    report["care_report"] = {
        "status": "incomplete",
        "failures": failures,
        "next_steps": next_steps or _next_steps_for_failures(failures),
    }
    return report


def _default_report_fn(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return write_openai_json_report(
        build_report_prompt_payload(
            {
                "plant": payload["plant"],
                "symptoms": payload["symptoms"],
                "care_habits": payload["care_habits"],
            },
            instruction=str(payload.get("instruction", "")),
        ),
        PLANT_REPORT_PROMPT,
    )


def _extract_model_guidance(
    model_report: Dict[str, Any],
    fields: Dict[str, Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    evidence = (
        fields["plant"]["evidence"]
        + fields["symptoms"]["evidence"]
        + fields["care_habits"]["evidence"]
    )
    confidence = _to_float(model_report.get("confidence", 0.5)) or 0.5
    diagnosis = _normalize_model_diagnosis(
        model_report.get("diagnosis"),
        confidence=confidence,
        evidence=evidence,
    )
    care_plan = _normalize_model_care_plan(
        model_report.get("care_plan"),
        confidence=diagnosis["confidence"] if diagnosis else confidence,
        evidence=evidence,
    )
    missing = []
    if diagnosis is None:
        missing.append("diagnosis")
    if care_plan is None:
        missing.append("care_plan")
    if missing:
        raise ValueError(
            "OpenAI report model did not return usable "
            + " and ".join(missing)
            + " guidance."
        )
    return diagnosis, care_plan


def _normalize_model_diagnosis(
    raw: Any,
    *,
    confidence: float,
    evidence: List[str],
) -> Dict[str, Any] | None:
    if isinstance(raw, dict):
        diagnosis = dict(raw)
        causes = diagnosis.get("likely_causes")
        if not isinstance(causes, list) or not causes:
            cause = first_text(
                diagnosis.get("cause"),
                diagnosis.get("likely_cause"),
                diagnosis.get("summary"),
            )
            basis = first_text(diagnosis.get("basis"), diagnosis.get("rationale"))
            if cause:
                diagnosis["likely_causes"] = [
                    {
                        "cause": cause,
                        "basis": basis or "Based on the collected plant photos and care-habits answer.",
                    }
                ]
        diagnosis["confidence"] = _to_float(diagnosis.get("confidence", confidence)) or confidence
        diagnosis.setdefault("evidence", evidence)
        diagnosis.setdefault("observed_issue", first_text(diagnosis.get("issue"), diagnosis.get("symptoms")))
        diagnosis.setdefault(
            "root_cause_summary",
            first_text(diagnosis.get("summary"), diagnosis.get("basis")),
        )
        if isinstance(diagnosis.get("likely_causes"), list) and diagnosis["likely_causes"]:
            return diagnosis
        return None
    if isinstance(raw, str) and raw.strip():
        return {
            "likely_causes": [
                {
                    "cause": raw.strip(),
                    "basis": "Based on the collected plant photos and care-habits answer.",
                }
            ],
            "confidence": confidence,
            "evidence": evidence,
        }
    return None


def _normalize_model_care_plan(
    raw: Any,
    *,
    confidence: float,
    evidence: List[str],
) -> Dict[str, Any] | None:
    if isinstance(raw, dict):
        care_plan = dict(raw)
        actions = care_plan.get("actions")
        if not isinstance(actions, list) or not actions:
            alternative = care_plan.get("steps") or care_plan.get("recommendations")
            if isinstance(alternative, list):
                care_plan["actions"] = [str(item) for item in alternative if str(item).strip()]
            else:
                action = first_text(alternative, care_plan.get("summary"), care_plan.get("plan"))
                if action:
                    care_plan["actions"] = [action]
        if not isinstance(care_plan.get("actions"), list) or not care_plan["actions"]:
            care_plan["actions"] = (
                listify(care_plan.get("immediate_actions"))
                + listify(care_plan.get("routine_adjustments"))
            )
        care_plan["confidence"] = _to_float(care_plan.get("confidence", confidence)) or confidence
        care_plan.setdefault("evidence", evidence)
        care_plan.setdefault("immediate_actions", listify(care_plan.get("urgent_actions")))
        care_plan.setdefault("routine_adjustments", listify(care_plan.get("adjustments")))
        if isinstance(care_plan.get("actions"), list) and care_plan["actions"]:
            return care_plan
        return None
    if isinstance(raw, list):
        actions = [str(item).strip() for item in raw if str(item).strip()]
        if actions:
            return {
                "actions": actions,
                "confidence": confidence,
                "evidence": evidence,
            }
    if isinstance(raw, str) and raw.strip():
        return {
            "actions": [raw.strip()],
            "confidence": confidence,
            "evidence": evidence,
        }
    return None


def _derive_care_guidance(
    fields: Dict[str, Dict[str, Any]]
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    symptoms = _lower_tokens(fields["symptoms"]["content"])
    habits = _lower_tokens(fields["care_habits"]["content"])
    causes: List[Dict[str, Any]] = []
    actions: List[str] = []
    immediate_actions: List[str] = []
    routine_adjustments: List[str] = []

    if _has_any(symptoms, "yellow", "yellowing", "soft stems") and _has_any(
        habits, "daily", "every day", "overwater"
    ):
        causes.append(
            {
                "cause": "Likely overwatering stress",
                "basis": "Yellowing/soft stems were observed and the gardener reported daily watering.",
            }
        )
        actions.extend(
            [
                "Pause watering until the top 2-3 cm of soil is dry.",
                "Check that the pot drains freely and empty standing water from the saucer.",
            ]
        )
        immediate_actions.extend(actions[-2:])
        routine_adjustments.append("Before watering, check soil moisture with a finger or moisture meter instead of following a fixed daily schedule.")

    if _has_any(habits, "low indoor", "low light", "dark"):
        causes.append(
            {
                "cause": "Insufficient light may be compounding the stress",
                "basis": "The plant was reported to live in low indoor light.",
            }
        )
        light_action = "Move the plant to bright indirect light and avoid harsh midday sun."
        actions.append(light_action)
        routine_adjustments.append(light_action)

    if not causes:
        causes.append(
            {
                "cause": "Insufficient evidence for a specific diagnosis",
                "basis": "The collected observations did not match a reliable local care rule.",
            }
        )
        actions.append("Retake clear photos and provide watering/light details before changing care.")
        immediate_actions.append("Retake clear whole-plant and close-up photos before making major care changes.")

    confidence = min(
        0.85,
        fields["plant"]["confidence"],
        fields["symptoms"]["confidence"],
        fields["care_habits"]["confidence"],
    )
    diagnosis = {
        "likely_causes": causes,
        "observed_issue": fields["symptoms"]["value"],
        "root_cause_summary": causes[0]["basis"],
        "confidence": confidence,
        "evidence": fields["symptoms"]["evidence"] + fields["care_habits"]["evidence"],
    }
    care_plan = {
        "actions": actions,
        "immediate_actions": immediate_actions or actions[:2],
        "routine_adjustments": routine_adjustments or actions[1:],
        "monitoring": "Recheck new growth and soil moisture over the next 7-10 days.",
        "escalation": "If stems keep softening, leaves collapse rapidly, or roots smell sour, inspect the roots and consider repotting into fresh, well-draining mix.",
        "confidence": confidence,
        "evidence": fields["symptoms"]["evidence"] + fields["care_habits"]["evidence"],
    }
    return diagnosis, care_plan


def _care_report_view(
    fields: Dict[str, Dict[str, Any]],
    diagnosis: Dict[str, Any],
    care_plan: Dict[str, Any],
    *,
    run_status: str | None,
    model_name: str,
    demo_used: bool,
) -> Dict[str, Any]:
    primary_cause = primary_cause_from_diagnosis(diagnosis)
    confidence = min(
        fields["plant"]["confidence"],
        fields["symptoms"]["confidence"],
        fields["care_habits"]["confidence"],
        _to_float(diagnosis.get("confidence", 0.0)),
        _to_float(care_plan.get("confidence", diagnosis.get("confidence", 0.0))),
    )
    return build_report_view(
        title="Plant Doctor care report",
        status="drafted" if run_status == "interrupted" else "submitted",
        subject_summary=_plant_summary(fields["plant"]),
        issue=first_text(
            diagnosis.get("observed_issue"),
            fields["symptoms"]["value"],
            "Visible plant stress was observed.",
        ),
        root_cause=primary_cause.get("cause", "Likely care stress"),
        root_cause_explanation=first_text(
            primary_cause.get("basis"),
            diagnosis.get("root_cause_summary"),
            "Based on the submitted photos and care routine.",
        ),
        recommendations=recommendations_from_plan(care_plan)[:6],
        monitoring=first_text(
            care_plan.get("monitoring"),
            "Watch new growth, leaf color, and soil moisture over the next 7-10 days.",
        ),
        escalation=first_text(
            care_plan.get("escalation"),
            "Escalate if symptoms spread quickly, stems collapse, or roots smell sour.",
        ),
        confidence=confidence,
        review_state="Ready for review" if run_status == "interrupted" else "Submitted",
        evidence_summary=_evidence_summary(fields, diagnosis),
        model=model_name,
        warnings=["Uses demo fixture data."] if demo_used else [],
        extra_sections=[
            {
                "key": "care_routine",
                "title": "Care Routine Shared",
                "items": [fields["care_habits"]["value"]],
                "kind": "paragraph",
            }
        ],
        aliases={
            "subject_summary": "plant_summary",
            "recommendations": "care_tips",
            "escalation": "when_to_escalate",
        },
        extra_fields={"care_routine_summary": fields["care_habits"]["value"]},
    )


def _plant_summary(field: Dict[str, Any]) -> str:
    content = field["content"]
    name = content.get("common_name") or content.get("species") or "Plant"
    health = content.get("health")
    if health:
        return f"{name} observed; current health appears {health}."
    return f"{name} observed from the whole-plant photo."


def _evidence_summary(
    fields: Dict[str, Dict[str, Any]],
    diagnosis: Dict[str, Any],
) -> List[str]:
    primary = primary_cause_from_diagnosis(diagnosis)
    return [
        f"Whole plant: {fields['plant']['value']}",
        f"Close-up: {fields['symptoms']['value']}",
        f"Care routine: {fields['care_habits']['value']}",
        f"Reasoning: {primary.get('basis', 'Diagnosis is based on the submitted evidence.')}",
    ]


def _summary(fields: Dict[str, Dict[str, Any]], diagnosis: Dict[str, Any]) -> str:
    plant_name = (
        fields["plant"]["content"].get("common_name")
        or fields["plant"]["content"].get("species")
        or "Plant"
    )
    cause = diagnosis["likely_causes"][0]["cause"]
    return f"{plant_name}: {cause}."


def _next_steps_for_failures(failures: List[Dict[str, str]]) -> List[str]:
    steps: List[str] = []
    failure_texts = [
        f"{item.get('field', '')} {item.get('reason', '')}".lower()
        for item in failures
    ]
    text = " ".join(failure_texts)
    if "openai" in text or "real provider" in text:
        steps.append("Set OPENAI_API_KEY and rerun with real vision analysis.")
    if any(
        "care_habits" in item
        or "care-habits answer" in item
        or "spoken care-habits" in item
        or "audio" in item
        for item in failure_texts
    ):
        steps.append("Collect a spoken care-habits answer through the ElevenLabs agent.")
    whole_photo_failed = any(
        "whole_plant" in item or "whole-plant photo" in item
        for item in failure_texts
    )
    closeup_photo_failed = any(
        "close_up" in item
        or "closeup" in item
        or "close-up photo" in item
        or "affected_leaves" in item
        for item in failure_texts
    )
    if whole_photo_failed and closeup_photo_failed:
        steps.append("Retake both the whole-plant and close-up photos.")
    elif whole_photo_failed:
        steps.append("Retake the whole-plant photo.")
    elif closeup_photo_failed:
        steps.append("Retake the close-up photo.")
    elif "image" in text or "photo" in text:
        steps.append("Retake the plant photos.")
    return steps or ["Fix the listed evidence gaps and rerun the Plant Doctor flow."]


def _lower_tokens(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(v).lower() for v in value.values())
    if isinstance(value, list):
        return " ".join(str(v).lower() for v in value)
    return str(value).lower()


def _has_any(haystack: str, *needles: str) -> bool:
    return any(needle in haystack for needle in needles)


def _to_float(raw: Any) -> float:
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
