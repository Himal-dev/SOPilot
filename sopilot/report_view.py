"""Reusable rich-report view shaping helpers."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from pydantic import BaseModel, Field


class ReportSection(BaseModel):
    key: str
    title: str
    items: list[str] = Field(default_factory=list)
    kind: str = "list"


class ReportView(BaseModel):
    title: str
    status: str = "drafted"
    summary: str = ""
    subject_summary: str = ""
    issue: str = ""
    root_cause: str = ""
    root_cause_explanation: str = ""
    recommendations: list[str] = Field(default_factory=list)
    monitoring: str = ""
    escalation: str = ""
    confidence: float = 0.0
    confidence_label: str = "Not enough evidence"
    review_state: str = ""
    evidence_summary: list[str] = Field(default_factory=list)
    model: str = ""
    warnings: list[str] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)


def build_report_view(
    *,
    title: str,
    status: str = "drafted",
    summary: str = "",
    subject_summary: str = "",
    issue: str = "",
    root_cause: str = "",
    root_cause_explanation: str = "",
    recommendations: Sequence[Any] = (),
    monitoring: str = "",
    escalation: str = "",
    confidence: float = 0.0,
    review_state: str = "",
    evidence_summary: Sequence[Any] = (),
    model: str = "",
    warnings: Sequence[Any] = (),
    extra_sections: Optional[Sequence[ReportSection | Mapping[str, Any]]] = None,
    aliases: Optional[Mapping[str, str]] = None,
    extra_fields: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    recs = dedupe_items(recommendations)
    evidence = dedupe_items(evidence_summary)
    view = ReportView(
        title=title,
        status=status,
        summary=summary,
        subject_summary=subject_summary,
        issue=issue,
        root_cause=root_cause,
        root_cause_explanation=root_cause_explanation,
        recommendations=recs,
        monitoring=monitoring,
        escalation=escalation,
        confidence=confidence,
        confidence_label=confidence_label(confidence),
        review_state=review_state,
        evidence_summary=evidence,
        model=model,
        warnings=dedupe_items(warnings),
        sections=_default_sections(
            root_cause_explanation=root_cause_explanation,
            recommendations=recs,
            monitoring=monitoring,
            escalation=escalation,
            evidence_summary=evidence,
            extra_sections=extra_sections,
        ),
    )
    data = view.model_dump()
    for source, alias in (aliases or {}).items():
        if source in data:
            data[alias] = data[source]
    if extra_fields:
        data.update(dict(extra_fields))
    return data


def recommendations_from_plan(plan: Mapping[str, Any]) -> list[str]:
    return dedupe_items(
        [
            *listify(plan.get("immediate_actions")),
            *listify(plan.get("routine_adjustments")),
            *listify(plan.get("actions")),
            *listify(plan.get("recommendations")),
            *listify(plan.get("steps")),
        ]
    )


def primary_cause_from_diagnosis(diagnosis: Mapping[str, Any]) -> dict[str, Any]:
    causes = diagnosis.get("likely_causes")
    if isinstance(causes, list) and causes and isinstance(causes[0], dict):
        return dict(causes[0])
    return {
        "cause": first_text(diagnosis.get("root_cause"), diagnosis.get("cause")),
        "basis": first_text(diagnosis.get("root_cause_summary"), diagnosis.get("basis")),
    }


def confidence_label(confidence: float) -> str:
    value = _to_float(confidence)
    if value >= 0.75:
        return "High confidence"
    if value >= 0.55:
        return "Moderate confidence"
    if value > 0:
        return "Low confidence"
    return "Not enough evidence"


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def dedupe_items(items: Sequence[Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        key = value.lower()
        if value and key not in seen:
            deduped.append(value)
            seen.add(key)
    return deduped


def _default_sections(
    *,
    root_cause_explanation: str,
    recommendations: Sequence[str],
    monitoring: str,
    escalation: str,
    evidence_summary: Sequence[str],
    extra_sections: Optional[Sequence[ReportSection | Mapping[str, Any]]],
) -> list[ReportSection]:
    sections = [
        ReportSection(
            key="root_cause_explanation",
            title="Why This Is Happening",
            items=listify(root_cause_explanation),
            kind="paragraph",
        ),
        ReportSection(
            key="recommendations",
            title="Recommended Actions",
            items=list(recommendations),
        ),
        ReportSection(
            key="monitoring",
            title="Monitor Next",
            items=listify(monitoring),
            kind="paragraph",
        ),
        ReportSection(
            key="escalation",
            title="When To Escalate",
            items=listify(escalation),
            kind="paragraph",
        ),
        ReportSection(key="evidence", title="Evidence Used", items=list(evidence_summary)),
    ]
    for section in extra_sections or []:
        parsed = section if isinstance(section, ReportSection) else ReportSection.model_validate(section)
        sections.append(parsed)
    return [section for section in sections if section.items]


def _to_float(raw: Any) -> float:
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
