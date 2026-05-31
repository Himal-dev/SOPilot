"""Reusable evidence-backed report readiness helpers.

Product reports still need domain-specific writing, but every app needs the
same reliability layer first: collect required output fields, detect missing or
fixture evidence, translate risks into user-facing failures, and tell the guide
which media should be retried without discarding good answers.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from sopilot.scaffold import AgentManifest


class ReportFieldSpec(BaseModel):
    name: str
    label: str = ""
    step_id: str = ""
    modality: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    missing_reason: str = ""
    retry_instruction: str = ""
    required: bool = True


class CollectedReportField(BaseModel):
    value: Any
    confidence: float
    content: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)


class ReportFailure(BaseModel):
    field: str
    reason: str
    kind: str = "evidence"
    step_id: str = ""
    modality: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    def public_dict(self) -> dict[str, str]:
        return {"field": self.field, "reason": self.reason}


class ReportReadiness(BaseModel):
    ready: bool
    fields: dict[str, dict[str, Any]]
    failures: list[ReportFailure] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    retry_media_fields: list[str] = Field(default_factory=list)
    demo_data_used: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list)

    def public_failures(self) -> list[dict[str, str]]:
        return [failure.public_dict() for failure in self.failures]


def report_field_specs_from_manifest(
    manifest: AgentManifest,
    *,
    include_fields: Optional[Sequence[str]] = None,
    overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[ReportFieldSpec]:
    """Create report field requirements from manifest media requirements."""
    include = set(include_fields or [])
    overrides = overrides or {}
    specs: list[ReportFieldSpec] = []
    for requirement in manifest.media_requirements:
        for field_name in requirement.produces:
            if include and field_name not in include:
                continue
            spec_data: dict[str, Any] = {
                "name": field_name,
                "label": _default_label(requirement.title, field_name),
                "step_id": requirement.step_id,
                "modality": requirement.modality,
                "evidence_refs": list(requirement.evidence_refs),
                "missing_reason": (
                    f"Missing reliable {_default_label(requirement.title, field_name)} evidence."
                ),
                "retry_instruction": _default_retry_instruction(requirement.modality, requirement.title),
                "required": requirement.required,
            }
            spec_data.update(overrides.get(field_name, {}))
            specs.append(ReportFieldSpec.model_validate(spec_data))
    return specs


def build_report_readiness(
    run_data: Mapping[str, Any],
    required_fields: Sequence[ReportFieldSpec | Mapping[str, Any]],
    *,
    allow_demo_data: bool = False,
    demo_data_next_step: str = "Run again with live provider output.",
) -> ReportReadiness:
    """Assess whether a run has enough reliable evidence for a report."""
    specs = [
        item if isinstance(item, ReportFieldSpec) else ReportFieldSpec.model_validate(item)
        for item in required_fields
    ]
    outputs = dict(run_data.get("step_outputs", {}) or {})
    evidence = list(run_data.get("evidence", []) or [])
    observations = list(run_data.get("observations", []) or [])
    risks = list(run_data.get("risks", []) or [])

    evidence_by_id = {item.get("id"): item for item in evidence if item.get("id")}
    fields: dict[str, dict[str, Any]] = {}
    failures: list[ReportFailure] = []

    for spec in specs:
        collected = _clean_field(outputs.get(spec.name), evidence_by_id)
        if collected is not None:
            fields[spec.name] = collected.model_dump()
        elif spec.required:
            failures.append(
                ReportFailure(
                    field=_failure_field(spec),
                    reason=spec.missing_reason
                    or f"Missing reliable {spec.label or spec.name.replace('_', ' ')} evidence.",
                    kind="missing_field",
                    step_id=spec.step_id,
                    modality=spec.modality,
                    evidence_refs=list(spec.evidence_refs),
                )
            )

    for obs in observations:
        failure = _observation_failure(obs, specs)
        if failure is not None:
            failures.append(failure)

    if not allow_demo_data:
        for spec in specs:
            field = fields.get(spec.name)
            if field and any(str(model).endswith(":stub") for model in field.get("models", [])):
                failures.append(
                    ReportFailure(
                        field=_failure_field(spec),
                        reason="Demo fixture data was used; real provider output is required.",
                        kind="demo_data",
                        step_id=spec.step_id,
                        modality=spec.modality,
                        evidence_refs=list(spec.evidence_refs),
                    )
                )

    for risk in risks:
        failures.append(_risk_failure(risk, specs))

    failures = _suppress_redundant_failures(failures)
    next_steps = _next_steps(failures, specs, demo_data_next_step=demo_data_next_step)
    retry_media_fields = _retry_media_fields(failures)
    demo_data_used = any(_is_demo_evidence(item) for item in evidence)
    return ReportReadiness(
        ready=not failures,
        fields=fields,
        failures=failures,
        next_steps=next_steps,
        retry_media_fields=retry_media_fields,
        demo_data_used=demo_data_used,
        evidence=_report_evidence(evidence),
    )


def incomplete_report_payload(
    failures: Sequence[ReportFailure | Mapping[str, Any]],
    next_steps: Sequence[str],
    *,
    summary: str = "Could not produce a reliable report.",
    report_key: str = "report",
) -> dict[str, Any]:
    parsed = [
        item if isinstance(item, ReportFailure) else ReportFailure.model_validate(item)
        for item in failures
    ]
    return {
        "summary": summary,
        "completed": False,
        report_key: {
            "status": "incomplete",
            "failures": [failure.public_dict() for failure in parsed],
            "next_steps": list(next_steps),
        },
    }


def _clean_field(
    field: Any,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> CollectedReportField | None:
    if not isinstance(field, dict):
        return None
    confidence = _to_float(field.get("confidence", 0.0))
    value = field.get("value")
    if confidence <= 0.0 or _is_blank(value):
        return None
    evidence_ids = [str(item) for item in list(field.get("evidence", []) or [])]
    models = [
        str(evidence_by_id[eid].get("model", ""))
        for eid in evidence_ids
        if eid in evidence_by_id
    ]
    content = field.get("content", {}) if isinstance(field.get("content"), dict) else {}
    return CollectedReportField(
        value=value,
        confidence=confidence,
        content=content,
        evidence=evidence_ids,
        models=models,
    )


def _observation_failure(
    obs: Mapping[str, Any],
    specs: Sequence[ReportFieldSpec],
) -> ReportFailure | None:
    summary = str(obs.get("summary", "") or "")
    confidence = _to_float(obs.get("confidence", 0.0))
    failed = confidence <= 0.0 or "failed:" in summary.lower()
    if not failed:
        return None
    spec = _spec_for_step(str(obs.get("step_id", "")), specs)
    return ReportFailure(
        field=_failure_field(spec) if spec else str(obs.get("source", "observation")),
        reason=summary or "Observation failed.",
        kind="observation_failed",
        step_id=str(obs.get("step_id", "")),
        modality=spec.modality if spec else str(obs.get("source", "")),
        evidence_refs=list(spec.evidence_refs) if spec else [],
    )


def _risk_failure(
    risk: Mapping[str, Any],
    specs: Sequence[ReportFieldSpec],
) -> ReportFailure:
    step_id = str(risk.get("step_id", "risk"))
    detail = str(risk.get("detail", risk.get("kind", "Risk flagged.")))
    spec = _spec_for_step(step_id, specs)
    field = _failure_field(spec) if spec else step_id
    if risk.get("kind") == "low_confidence" and spec:
        label = spec.label or spec.name.replace("_", " ")
        detail = f"{label.capitalize()} confidence is too low for a reliable report ({detail})"
    return ReportFailure(
        field=field,
        reason=detail,
        kind=str(risk.get("kind", "risk")),
        step_id=step_id,
        modality=spec.modality if spec else "",
        evidence_refs=list(spec.evidence_refs) if spec else [],
    )


def _next_steps(
    failures: Sequence[ReportFailure],
    specs: Sequence[ReportFieldSpec],
    *,
    demo_data_next_step: str,
) -> list[str]:
    steps: list[str] = []
    if any(failure.kind == "demo_data" for failure in failures):
        steps.append(demo_data_next_step)
    for failure in failures:
        spec = _spec_for_failure(failure, specs)
        if spec and spec.retry_instruction:
            steps.append(spec.retry_instruction)
    if not steps and failures:
        steps.append("Fix the listed evidence gaps and rerun the flow.")
    return _dedupe(steps)


def _suppress_redundant_failures(
    failures: Sequence[ReportFailure],
) -> list[ReportFailure]:
    missing_fields = {failure.field for failure in failures if failure.kind == "missing_field"}
    redundant_when_missing = {"observation_failed", "low_confidence"}
    return [
        failure
        for failure in failures
        if not (failure.field in missing_fields and failure.kind in redundant_when_missing)
    ]


def _retry_media_fields(failures: Sequence[ReportFailure]) -> list[str]:
    fields: list[str] = []
    for failure in failures:
        if failure.modality not in {"vision", "voice"}:
            continue
        fields.extend(failure.evidence_refs or [failure.field])
    return _dedupe(fields)


def _spec_for_failure(
    failure: ReportFailure,
    specs: Sequence[ReportFieldSpec],
) -> ReportFieldSpec | None:
    for spec in specs:
        if failure.step_id and spec.step_id == failure.step_id:
            return spec
        if failure.field == spec.name or failure.field in spec.evidence_refs:
            return spec
    return None


def _spec_for_step(step_id: str, specs: Sequence[ReportFieldSpec]) -> ReportFieldSpec | None:
    return next((spec for spec in specs if spec.step_id == step_id), None)


def _failure_field(spec: ReportFieldSpec) -> str:
    return spec.evidence_refs[0] if spec.evidence_refs else spec.name


def _default_label(title: str, field_name: str) -> str:
    label = (title or field_name).strip().lower()
    return label or field_name.replace("_", " ")


def _default_retry_instruction(modality: str, title: str) -> str:
    if modality == "vision":
        return f"Retake: {title.strip()}."
    if modality == "voice":
        return f"Collect answer again: {title.strip()}."
    return "Retry the missing evidence."


def _report_evidence(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in evidence if item.get("model") != "planner-reason"]


def _is_demo_evidence(item: Mapping[str, Any]) -> bool:
    return str(item.get("model", "")).endswith(":stub")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


def _dedupe(items: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = str(item).strip()
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def _to_float(raw: Any) -> float:
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
