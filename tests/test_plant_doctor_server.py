"""Two-phase HITL run: start until interrupt, then resume to finalize."""

import io
import json
from pathlib import Path

import pytest

from sopilot.runner import resume_run, start_run

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def test_start_run_pauses_at_review(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    started = start_run(AGENT, media={}, db_path=db)
    assert started["status"] == "interrupted"
    assert started["review_request"]["trigger"] == "final_submit"
    assert started["thread_id"]
    assert started["drafted_output"]


def test_resume_run_approves_and_finalizes(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    started = start_run(AGENT, media={}, db_path=db)
    final = resume_run(
        AGENT,
        thread_id=started["thread_id"],
        decision={"decision": "approve", "reviewer": "ui"},
        db_path=db,
    )
    assert final["status"] == "completed"
    assert "care_report" in final["final_output"]
    assert final["evidence"]


def test_resume_run_reject_halts(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    started = start_run(AGENT, media={}, db_path=db)
    final = resume_run(
        AGENT,
        thread_id=started["thread_id"],
        decision={"decision": "reject", "reviewer": "ui", "note": "needs work"},
        db_path=db,
    )
    assert final["status"] == "rejected"


fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_hosted_auth_env(monkeypatch):
    monkeypatch.delenv("PLANT_DOCTOR_APP_TOKEN", raising=False)
    monkeypatch.delenv("PLANT_DOCTOR_TRIAL_CODE", raising=False)


def _client():
    from app.server import create_app

    return TestClient(create_app())


def test_health_ok():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_web_config_marks_auth_required_when_trial_code_exists(monkeypatch):
    monkeypatch.setenv("PLANT_DOCTOR_APP_TOKEN", "trial-token")
    monkeypatch.setenv("PLANT_DOCTOR_TRIAL_CODE", "invite-123")
    resp = _client().get("/config.js")
    assert resp.status_code == 200
    assert 'window.PLANT_DOCTOR_APP_TOKEN = "trial-token";' in resp.text
    assert "window.PLANT_DOCTOR_AUTH_REQUIRED = true;" in resp.text
    assert "invite-123" not in resp.text


def test_elevenlabs_session_reports_missing_config(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_PLANT_DOCTOR_AGENT_ID", raising=False)
    resp = _client().get("/api/elevenlabs/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert "captureWholePlantPhoto" in body["required_client_tools"]


def test_app_token_gate_blocks_when_configured(monkeypatch):
    monkeypatch.setenv("PLANT_DOCTOR_APP_TOKEN", "trial-token")
    client = _client()
    blocked = client.get("/api/elevenlabs/session")
    assert blocked.status_code == 401
    allowed = client.get("/api/elevenlabs/session", headers={"x-app-token": "trial-token"})
    assert allowed.status_code == 200


def test_trial_code_gate_blocks_live_endpoints_when_configured(monkeypatch):
    monkeypatch.setenv("PLANT_DOCTOR_APP_TOKEN", "trial-token")
    monkeypatch.setenv("PLANT_DOCTOR_TRIAL_CODE", "invite-123")
    client = _client()
    token_header = {"x-app-token": "trial-token"}

    auth_missing_code = client.get("/api/auth/check", headers=token_header)
    assert auth_missing_code.status_code == 401
    assert auth_missing_code.json()["required"] is True

    blocked = client.get("/api/elevenlabs/session", headers=token_header)
    assert blocked.status_code == 401

    allowed = client.get(
        "/api/elevenlabs/session",
        headers={**token_header, "x-trial-code": "invite-123", "x-session-id": "trial-session"},
    )
    assert allowed.status_code == 200

    auth_ok = client.get(
        "/api/auth/check",
        headers={**token_header, "x-trial-code": "invite-123", "x-session-id": "trial-session"},
    )
    assert auth_ok.status_code == 200
    assert auth_ok.json() == {"ok": True, "required": True}


def test_elevenlabs_public_agent_session(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_PLANT_DOCTOR_AGENT_ID", "agent_test")
    monkeypatch.setenv("ELEVENLABS_AGENT_PUBLIC", "true")
    resp = _client().get("/api/elevenlabs/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["agent_id"] == "agent_test"
    assert body["auth"] == "public"
    instructions = body["dynamic_variables"]["plant_doctor_instructions"]
    assert "captureWholePlantPhoto" in instructions
    assert "captureCloseupPhoto" in instructions
    assert "recordCareHabitAnswer" in instructions
    assert "one at a time" in instructions
    assert "submitPlantDoctorRun" in instructions
    assert "final_spoken_summary" in instructions
    assert "speech finishes" in instructions


def test_elevenlabs_private_agent_session_uses_server_token(monkeypatch):
    import app.server as server

    monkeypatch.setenv("ELEVENLABS_PLANT_DOCTOR_AGENT_ID", "agent_private")
    monkeypatch.delenv("ELEVENLABS_AGENT_PUBLIC", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret-key")
    monkeypatch.setattr(
        server,
        "_get_elevenlabs_conversation_token",
        lambda agent_id, api_key: f"token-for-{agent_id}",
    )
    resp = _client().get("/api/elevenlabs/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["conversation_token"] == "token-for-agent_private"
    assert body["auth"] == "private_webrtc"


def test_elevenlabs_setup_payload_contains_agent_contract():
    resp = _client().get("/api/elevenlabs/setup")
    assert resp.status_code == 200
    body = resp.json()
    tool_names = {tool["name"] for tool in body["client_tools"]}
    assert {
        "getPlantDoctorState",
        "captureWholePlantPhoto",
        "captureCloseupPhoto",
        "recordCareHabitAnswer",
        "submitPlantDoctorRun",
    }.issubset(tool_names)
    record_tool = next(
        tool for tool in body["client_tools"] if tool["name"] == "recordCareHabitAnswer"
    )
    assert record_tool["expects_response"] is True
    assert record_tool["parameters"]["additionalProperties"] is False
    assert record_tool["parameters"]["required"] == ["topic", "answer"]
    assert record_tool["parameters"]["properties"]["topic"]["enum"] == [
        "watering",
        "light_location",
        "drainage_soil",
        "recent_changes_pests",
    ]
    assert record_tool["parameters"]["properties"]["answer"]["minLength"] == 1
    submit_tool = next(
        tool for tool in body["client_tools"] if tool["name"] == "submitPlantDoctorRun"
    )
    assert submit_tool["expects_response"] is True
    assert "care_habits_transcript" in submit_tool["parameters"]["required"]


def test_manifest_endpoint_exposes_collection_contract():
    resp = _client().get("/api/manifest")
    assert resp.status_code == 200
    body = resp.json()
    refs = [item["evidence_refs"] for item in body["media_requirements"]]
    assert ["whole_plant_photo"] in refs
    assert ["closeup_photo"] in refs
    assert ["care_habits_audio"] in refs
    voice = next(item for item in body["media_requirements"] if item["modality"] == "voice")
    assert len(voice["drilldown_questions"]) == 4


def test_live_run_without_openai_key_reports_failure(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client()
    run = client.post("/api/run")
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "failed"
    assert body["final_output"]["completed"] is False
    assert "OPENAI_API_KEY" in body["final_output"]["care_report"]["failures"][0]["reason"]


def test_run_then_decision_completes_with_explicit_demo_data():
    client = _client()
    files = [
        ("whole_plant_photo", ("whole.jpg", io.BytesIO(b"img1"), "image/jpeg")),
        ("closeup_photo", ("close.jpg", io.BytesIO(b"img2"), "image/jpeg")),
        ("care_habits_audio", ("a.wav", io.BytesIO(b"aud"), "audio/wav")),
    ]
    run = client.post("/api/run", data={"allow_demo_data": "true"}, files=files)
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "interrupted"
    assert body["drafted_output"]["completed"] is True
    assert "Submit the plant care report" not in json.dumps(body["drafted_output"])
    assert body["drafted_output"]["care_plan"]["actions"]
    thread_id = body["thread_id"]

    dec = client.post(
        "/api/decision",
        json={
            "thread_id": thread_id,
            "db_path": body["db_path"],
            "decision": "approve",
            "reviewer": "ui",
            "allow_demo_data": True,
        },
    )
    assert dec.status_code == 200
    final = dec.json()
    assert final["status"] == "completed"
    assert final["final_output"]["completed"] is True
    assert "Submit the plant care report" not in json.dumps(final["final_output"])
    latest = json.loads((AGENT / "sample_outputs" / "latest_run.json").read_text())
    assert "Submit the plant care report" not in json.dumps(latest)


def test_run_auto_approves_for_hosted_trial(monkeypatch):
    monkeypatch.setenv("PLANT_DOCTOR_AUTO_APPROVE", "true")
    client = _client()
    files = [
        ("whole_plant_photo", ("whole.jpg", io.BytesIO(b"img1"), "image/jpeg")),
        ("closeup_photo", ("close.jpg", io.BytesIO(b"img2"), "image/jpeg")),
    ]
    run = client.post(
        "/api/run",
        data={
            "allow_demo_data": "true",
            "care_habits_transcript": "watering weekly; bright indirect light; drainage holes; recently moved near a window",
        },
        files=files,
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["final_output"]["completed"] is True


def test_server_media_map_matches_compiled_step_ids():
    from app.server import _plant_step_ids

    step_ids = _plant_step_ids()
    vision_cues = json.loads((AGENT / "sample_inputs" / "vision_cues.json").read_text())
    voice_cues = json.loads((AGENT / "sample_inputs" / "voice_cues.json").read_text())
    assert set(step_ids["vision"].values()).issubset(vision_cues)
    assert step_ids["voice"] in voice_cues
