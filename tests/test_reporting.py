"""Reusable report readiness helpers for app-facing reports."""

from pathlib import Path

from sopilot.reporting import (
    ReportFieldSpec,
    build_report_readiness,
    incomplete_report_payload,
    report_field_specs_from_manifest,
)
from sopilot.scaffold import build_agent_manifest

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def _run_data():
    evidence = [
        {"id": "ev1", "model": "vision:openai", "step_id": "capture_whole"},
        {"id": "ev2", "model": "vision:openai", "step_id": "capture_close"},
        {"id": "ev3", "model": "elevenlabs-agent", "step_id": "ask_habits"},
    ]
    return {
        "status": "completed",
        "evidence": evidence,
        "observations": [],
        "risks": [],
        "step_outputs": {
            "plant": {
                "value": "Pothos plant observed.",
                "confidence": 0.88,
                "content": {"common_name": "Pothos"},
                "evidence": ["ev1"],
            },
            "symptoms": {
                "value": "Yellow leaves.",
                "confidence": 0.82,
                "content": {"symptoms": ["yellow leaves"]},
                "evidence": ["ev2"],
            },
            "care_habits": {
                "value": "Watered daily in low light.",
                "confidence": 0.9,
                "content": {"watering": "daily", "light": "low"},
                "evidence": ["ev3"],
            },
        },
    }


def test_report_specs_can_be_derived_from_manifest_with_overrides():
    manifest = build_agent_manifest(AGENT)
    specs = report_field_specs_from_manifest(
        manifest,
        include_fields=["plant", "symptoms", "care_habits"],
        overrides={
            "plant": {
                "label": "whole-plant photo",
                "retry_instruction": "Retake the whole-plant photo.",
            }
        },
    )

    assert [spec.name for spec in specs] == ["plant", "symptoms", "care_habits"]
    assert specs[0].step_id == "capture_the_whole_plant_in_frame"
    assert specs[0].evidence_refs == ["whole_plant_photo"]
    assert specs[0].retry_instruction == "Retake the whole-plant photo."


def test_report_readiness_preserves_good_answers_and_retries_only_weak_media():
    manifest = build_agent_manifest(AGENT)
    specs = report_field_specs_from_manifest(
        manifest,
        include_fields=["plant", "symptoms", "care_habits"],
        overrides={
            "symptoms": {
                "label": "close-up photo",
                "retry_instruction": "Retake the close-up photo.",
            }
        },
    )
    data = _run_data()
    data["risks"] = [
        {
            "step_id": "capture_a_close_up_of_the_affected_leaves_or_ste",
            "kind": "low_confidence",
            "severity": "warning",
            "detail": "confidence 0.52 < min 0.60; recommend recapture/review.",
        }
    ]

    readiness = build_report_readiness(data, specs)

    assert readiness.ready is False
    assert readiness.fields["care_habits"]["value"] == "Watered daily in low light."
    assert readiness.failures[0].field == "closeup_photo"
    assert "close-up photo confidence" in readiness.failures[0].reason.lower()
    assert readiness.retry_media_fields == ["closeup_photo"]
    assert readiness.next_steps == ["Retake the close-up photo."]


def test_report_readiness_blocks_fixture_data_without_demo_mode():
    specs = [
        ReportFieldSpec(
            name="plant",
            label="whole-plant photo",
            modality="vision",
            evidence_refs=["whole_plant_photo"],
            retry_instruction="Retake the whole-plant photo.",
        )
    ]
    data = _run_data()
    data["evidence"][0]["model"] = "vision:stub"

    readiness = build_report_readiness(
        data,
        specs,
        demo_data_next_step="Set provider key and rerun live.",
    )

    assert readiness.ready is False
    assert readiness.demo_data_used is True
    assert readiness.failures[0].kind == "demo_data"
    assert readiness.next_steps[0] == "Set provider key and rerun live."


def test_missing_field_suppresses_duplicate_observation_and_low_confidence_noise():
    specs = [
        ReportFieldSpec(
            name="plant",
            label="whole-plant photo",
            step_id="capture_the_whole_plant_in_frame",
            modality="vision",
            evidence_refs=["whole_plant_photo"],
            missing_reason="Missing whole-plant photo.",
            retry_instruction="Retake the whole-plant photo.",
        )
    ]
    data = _run_data()
    data["step_outputs"]["plant"] = {
        "value": "No image provided for this step.",
        "confidence": 0.0,
        "content": {},
        "evidence": ["ev1"],
    }
    data["observations"] = [
        {
            "step_id": "capture_the_whole_plant_in_frame",
            "source": "vision",
            "summary": "No image provided for this step.",
            "confidence": 0.0,
        }
    ]
    data["risks"] = [
        {
            "step_id": "capture_the_whole_plant_in_frame",
            "kind": "low_confidence",
            "detail": "confidence 0.00 < min 0.40; recommend recapture/review.",
        }
    ]

    readiness = build_report_readiness(data, specs)

    assert readiness.public_failures() == [
        {"field": "whole_plant_photo", "reason": "Missing whole-plant photo."}
    ]
    assert readiness.next_steps == ["Retake the whole-plant photo."]


def test_report_readiness_accepts_live_complete_evidence():
    manifest = build_agent_manifest(AGENT)
    specs = report_field_specs_from_manifest(
        manifest,
        include_fields=["plant", "symptoms", "care_habits"],
    )

    readiness = build_report_readiness(_run_data(), specs)

    assert readiness.ready is True
    assert readiness.failures == []
    assert readiness.retry_media_fields == []
    assert readiness.fields["plant"]["content"]["common_name"] == "Pothos"


def test_incomplete_report_payload_can_use_product_report_key():
    payload = incomplete_report_payload(
        [{"field": "photo", "reason": "Missing photo."}],
        ["Retake the photo."],
        summary="Could not report.",
        report_key="care_report",
    )

    assert payload["summary"] == "Could not report."
    assert payload["care_report"]["status"] == "incomplete"
    assert payload["care_report"]["next_steps"] == ["Retake the photo."]
