"""Reusable rich-report view shaping helpers."""

from sopilot.report_view import (
    build_report_view,
    confidence_label,
    primary_cause_from_diagnosis,
    recommendations_from_plan,
)


def test_build_report_view_creates_sections_and_aliases():
    view = build_report_view(
        title="Care report",
        status="submitted",
        subject_summary="Pothos observed.",
        issue="Yellow leaves.",
        root_cause="Overwatering",
        root_cause_explanation="Daily watering plus soft stems.",
        recommendations=["Pause watering.", "Pause watering.", "Check drainage."],
        monitoring="Watch new growth.",
        escalation="Check roots if stems soften.",
        confidence=0.77,
        review_state="Submitted",
        evidence_summary=["Whole plant: pothos", "Whole plant: pothos", "Care routine: daily"],
        aliases={"subject_summary": "plant_summary", "recommendations": "care_tips"},
        extra_fields={"care_routine_summary": "Watered daily."},
    )

    assert view["title"] == "Care report"
    assert view["confidence_label"] == "High confidence"
    assert view["plant_summary"] == "Pothos observed."
    assert view["care_tips"] == ["Pause watering.", "Check drainage."]
    assert view["care_routine_summary"] == "Watered daily."
    assert [section["key"] for section in view["sections"]] == [
        "root_cause_explanation",
        "recommendations",
        "monitoring",
        "escalation",
        "evidence",
    ]
    assert view["evidence_summary"] == ["Whole plant: pothos", "Care routine: daily"]


def test_recommendations_from_plan_merges_common_action_fields():
    plan = {
        "immediate_actions": ["Pause watering."],
        "routine_adjustments": ["Check soil before watering."],
        "actions": ["Pause watering.", "Move to bright indirect light."],
        "recommendations": ["Check soil before watering."],
    }

    assert recommendations_from_plan(plan) == [
        "Pause watering.",
        "Check soil before watering.",
        "Move to bright indirect light.",
    ]


def test_primary_cause_and_confidence_labels_are_generic():
    diagnosis = {
        "likely_causes": [
            {"cause": "Low light stress", "basis": "Plant is far from a window."}
        ]
    }
    assert primary_cause_from_diagnosis(diagnosis)["cause"] == "Low light stress"
    assert confidence_label(0.74) == "Moderate confidence"
    assert confidence_label(0.2) == "Low confidence"
    assert confidence_label(0) == "Not enough evidence"
