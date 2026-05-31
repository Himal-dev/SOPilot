"""Plant Doctor report assembly avoids placeholders and can use model output."""

from app.plant_doctor_report import build_plant_care_report


def _run_data(model_suffix="openai"):
    evidence = [
        {"id": "ev1", "model": f"vision:{model_suffix}", "step_id": "plant"},
        {"id": "ev2", "model": f"vision:{model_suffix}", "step_id": "symptoms"},
        {"id": "ev3", "model": "elevenlabs-agent", "step_id": "habits"},
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
                "value": "Yellow older leaves and soft stems.",
                "confidence": 0.82,
                "content": {"symptoms": ["yellow older leaves", "soft stems"]},
                "evidence": ["ev2"],
            },
            "care_habits": {
                "value": "The gardener waters daily in low light.",
                "confidence": 0.9,
                "content": {"watering": "daily", "light": "low indoor"},
                "evidence": ["ev3"],
            },
        },
    }


def test_model_report_is_used_when_available():
    def report_fn(payload):
        assert payload["plant"]["content"]["common_name"] == "Pothos"
        return {
            "summary": "Pothos: likely overwatering.",
            "diagnosis": {
                "likely_causes": [{"cause": "Overwatering", "basis": "Daily watering plus soft stems."}],
                "observed_issue": "Yellowing lower leaves and soft stems.",
                "root_cause_summary": "Water is likely staying around the roots too long.",
                "confidence": 0.77,
            },
            "care_plan": {
                "actions": ["Let soil dry before watering."],
                "immediate_actions": ["Pause watering until the top soil dries."],
                "routine_adjustments": ["Water only after checking soil moisture."],
                "monitoring": "Watch new growth over the next week.",
                "escalation": "Check roots if stems continue softening.",
                "confidence": 0.77,
            },
            "model": "test-model",
        }

    report = build_plant_care_report(_run_data(), report_fn=report_fn)
    assert report["diagnosis"]["likely_causes"][0]["cause"] == "Overwatering"
    assert report["care_plan"]["actions"] == ["Let soil dry before watering."]
    assert report["care_report"]["title"] == "Plant Doctor care report"
    assert report["care_report"]["root_cause"] == "Overwatering"
    assert "Pause watering" in report["care_report"]["care_tips"][0]
    assert "Pothos" in report["care_report"]["plant_summary"]
    assert report["care_report"]["model"] == "test-model"
    assert [section["key"] for section in report["care_report"]["sections"]] == [
        "root_cause_explanation",
        "recommendations",
        "monitoring",
        "escalation",
        "evidence",
        "care_routine",
    ]
    assert report["care_report"]["sections"][-1]["items"] == [
        "The gardener waters daily in low light."
    ]


def test_string_and_list_model_guidance_is_normalized():
    def report_fn(_payload):
        return {
            "summary": "Pothos: likely overwatering.",
            "diagnosis": "Likely overwatering stress",
            "care_plan": ["Let soil dry before watering.", "Move to bright indirect light."],
            "confidence": 0.66,
            "model": "test-model",
        }

    report = build_plant_care_report(_run_data(), report_fn=report_fn)
    assert report["completed"] is True
    assert report["diagnosis"]["likely_causes"][0]["cause"] == "Likely overwatering stress"
    assert report["care_plan"]["actions"] == [
        "Let soil dry before watering.",
        "Move to bright indirect light.",
    ]
    assert report["care_report"]["confidence"] == 0.66


def test_missing_model_guidance_returns_incomplete_report():
    def report_fn(_payload):
        return {
            "summary": "I could not decide.",
            "model": "test-model",
        }

    report = build_plant_care_report(_run_data(), report_fn=report_fn)
    assert report["completed"] is False
    assert report["care_report"]["status"] == "incomplete"
    assert report["care_report"]["failures"][0]["field"] == "report_model"
    assert "diagnosis" in report["care_report"]["failures"][0]["reason"]


def test_low_confidence_photo_risk_keeps_care_habits_and_asks_for_photo():
    data = _run_data()
    data["risks"] = [
        {
            "step_id": "capture_a_close_up_of_the_affected_leaves_or_ste",
            "kind": "low_confidence",
            "severity": "warning",
            "detail": "confidence 0.52 < min 0.60; recommend recapture/review.",
        }
    ]

    report = build_plant_care_report(data)

    assert report["completed"] is False
    assert report["care_habits"]["value"] == "The gardener waters daily in low light."
    assert "close-up photo confidence" in report["care_report"]["failures"][0]["reason"].lower()
    assert report["care_report"]["next_steps"] == ["Retake the close-up photo."]


def test_missing_whole_plant_photo_with_care_habits_asks_only_for_whole_photo():
    data = _run_data()
    data["step_outputs"]["plant"] = {
        "value": "",
        "confidence": 0.0,
        "content": {},
        "evidence": [],
    }

    report = build_plant_care_report(data)

    assert report["completed"] is False
    assert report["care_habits"]["value"] == "The gardener waters daily in low light."
    assert report["care_report"]["failures"] == [
        {
            "field": "whole_plant_photo",
            "reason": "Missing reliable whole-plant photo evidence for plant identification.",
        }
    ]
    assert report["care_report"]["next_steps"] == ["Retake the whole-plant photo."]


def test_missing_closeup_photo_with_care_habits_asks_only_for_closeup_photo():
    data = _run_data()
    data["step_outputs"]["symptoms"] = {
        "value": "",
        "confidence": 0.0,
        "content": {},
        "evidence": [],
    }

    report = build_plant_care_report(data)

    assert report["completed"] is False
    assert report["care_habits"]["value"] == "The gardener waters daily in low light."
    assert report["care_report"]["failures"] == [
        {
            "field": "closeup_photo",
            "reason": "Missing reliable close-up photo evidence for visible symptoms.",
        }
    ]
    assert report["care_report"]["next_steps"] == ["Retake the close-up photo."]


def test_stub_data_fails_without_explicit_demo_mode():
    report = build_plant_care_report(_run_data("stub"))
    assert report["completed"] is False
    assert report["care_report"]["status"] == "incomplete"
    assert "Demo fixture data" in report["care_report"]["failures"][0]["reason"]
