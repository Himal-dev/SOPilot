"""FastAPI server for the Plant Doctor demo.

The server implements a collect-then-run flow:
- upload photos and audio to start the SOP run,
- pause at the LangGraph HITL interrupt,
- resume with an explicit review decision,
- optionally synthesize a spoken care plan.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.plant_doctor_report import build_plant_care_report
from sopilot.conversation import (
    RecordTopic,
    build_client_tool_configs,
    build_client_tool_summary,
    build_guided_instructions,
    build_guided_tool_names,
)
from sopilot.media import MediaAsset, build_media_map
from sopilot.runner import resume_run, start_run
from sopilot.scaffold import build_agent_manifest
from sopilot.session_logging import log_session_event, session_id_from_request
from sopilot.web_runtime import install_api_security

REPO = Path(__file__).resolve().parents[1]
AGENT = REPO / "examples" / "plant_doctor_agent"
WEB = Path(__file__).resolve().parent / "web"

_PLANT_RECORD_TOPICS = [
    RecordTopic(key="watering", label="watering routine"),
    RecordTopic(key="light_location", label="light and location"),
    RecordTopic(key="drainage_soil", label="pot drainage and soil condition"),
    RecordTopic(key="recent_changes_pests", label="recent changes or pests"),
]

_PLANT_STRUCTURED_PROPERTIES = {
    "watering_frequency": {"type": "string"},
    "watering_amount": {"type": "string"},
    "light_exposure": {"type": "string"},
    "location": {"type": "string"},
    "pot_has_drainage": {"type": "string"},
    "soil_condition": {"type": "string"},
    "recent_changes": {"type": "string"},
    "pests_seen": {"type": "string"},
}

_PLANT_CAPTURE_TOOL_OVERRIDES = {
    "whole_plant_photo": "captureWholePlantPhoto",
    "closeup_photo": "captureCloseupPhoto",
}


def create_app() -> FastAPI:
    app = FastAPI(title="SOPilot Plant Doctor")
    install_api_security(
        app,
        token_env="PLANT_DOCTOR_APP_TOKEN",
        access_code_env="PLANT_DOCTOR_TRIAL_CODE",
        cors_origins_env="PLANT_DOCTOR_CORS_ORIGINS",
    )

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True}

    @app.get("/config.js", include_in_schema=False)
    def web_config() -> Response:
        return Response(_web_config_js(), media_type="application/javascript")

    @app.get("/api/auth/check")
    def auth_check(request: Request) -> JSONResponse:
        required = bool(os.environ.get("PLANT_DOCTOR_TRIAL_CODE", ""))
        ok = (not required) or request.headers.get("x-trial-code") == os.environ.get(
            "PLANT_DOCTOR_TRIAL_CODE"
        )
        log_session_event(
            "auth_check",
            app="plant_doctor",
            session_id=session_id_from_request(request),
            ok=ok,
            required=required,
        )
        status = 200 if ok else 401
        return JSONResponse({"ok": ok, "required": required}, status_code=status)

    @app.get("/api/elevenlabs/session")
    def elevenlabs_session(request: Request) -> JSONResponse:
        session_id = session_id_from_request(request)
        agent_id = os.environ.get("ELEVENLABS_PLANT_DOCTOR_AGENT_ID") or os.environ.get(
            "ELEVENLABS_AGENT_ID", ""
        )
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        public_agent = _env_bool("ELEVENLABS_AGENT_PUBLIC", False)
        if not agent_id:
            _log_guide_session(session_id, enabled=False, reason="missing_agent_id")
            return JSONResponse(
                {
                    "enabled": False,
                    "reason": "ELEVENLABS_PLANT_DOCTOR_AGENT_ID or ELEVENLABS_AGENT_ID is not set.",
                    "required_client_tools": _elevenlabs_client_tools(),
                }
            )
        if public_agent:
            _log_guide_session(session_id, enabled=True, auth="public")
            return JSONResponse(
                {
                    "enabled": True,
                    "agent_id": agent_id,
                    "auth": "public",
                    "dynamic_variables": _agent_dynamic_variables(),
                    "required_client_tools": _elevenlabs_client_tools(),
                }
            )
        if not api_key:
            _log_guide_session(session_id, enabled=False, reason="missing_elevenlabs_key")
            return JSONResponse(
                {
                    "enabled": False,
                    "reason": "ELEVENLABS_API_KEY is required for private agent sessions.",
                    "required_client_tools": _elevenlabs_client_tools(),
                }
            )
        try:
            token = _get_elevenlabs_conversation_token(agent_id, api_key)
        except Exception as exc:
            _log_guide_session(session_id, enabled=False, reason="token_error")
            return JSONResponse(
                {
                    "enabled": False,
                    "reason": f"Could not create ElevenLabs conversation token: {exc}",
                    "required_client_tools": _elevenlabs_client_tools(),
                },
                status_code=502,
            )
        _log_guide_session(session_id, enabled=True, auth="private_webrtc")
        return JSONResponse(
            {
                "enabled": True,
                "conversation_token": token,
                "auth": "private_webrtc",
                "dynamic_variables": _agent_dynamic_variables(),
                "required_client_tools": _elevenlabs_client_tools(),
            }
        )

    @app.get("/api/elevenlabs/setup")
    def elevenlabs_setup() -> Dict[str, Any]:
        return _elevenlabs_setup_payload()

    @app.get("/api/manifest")
    def manifest() -> Dict[str, Any]:
        return _plant_manifest().model_dump()

    @app.post("/api/run")
    async def run(
        request: Request,
        whole_plant_photo: Optional[UploadFile] = File(default=None),
        closeup_photo: Optional[UploadFile] = File(default=None),
        care_habits_audio: Optional[UploadFile] = File(default=None),
        care_habits_transcript: str = Form(default=""),
        care_habits_json: str = Form(default=""),
        allow_demo_data: bool = Form(default=False),
    ) -> JSONResponse:
        client_session_id = session_id_from_request(request)
        if not allow_demo_data and not os.environ.get("OPENAI_API_KEY"):
            failure = _configuration_failure(
                "OPENAI_API_KEY is required for a live Plant Doctor report.",
                "Set OPENAI_API_KEY and retry with real photos.",
            )
            _log_run_result(
                client_session_id,
                status="failed",
                completed=False,
                failure_count=1,
                reason="missing_openai_key",
            )
            return JSONResponse({"status": "failed", "final_output": failure})

        assets: Dict[str, Any] = {}
        for field, upload in {
            "whole_plant_photo": whole_plant_photo,
            "closeup_photo": closeup_photo,
        }.items():
            if upload is not None:
                assets[field] = MediaAsset.from_bytes(
                    field,
                    await upload.read(),
                    mime=upload.content_type or "image/jpeg",
                    filename=upload.filename or f"{field}.jpg",
                )

        if care_habits_audio is not None:
            assets["care_habits_audio"] = MediaAsset.from_bytes(
                "care_habits_audio",
                await care_habits_audio.read(),
                mime=care_habits_audio.content_type or "audio/webm",
                filename=care_habits_audio.filename or "answer.webm",
            )
        elif care_habits_transcript.strip():
            assets["care_habits_audio"] = MediaAsset.from_transcript(
                "care_habits_audio",
                care_habits_transcript.strip(),
                recording_id="care_habits_agent_transcript",
                content=_parse_json_object(care_habits_json),
                model="elevenlabs-agent",
            )

        media = build_media_map(
            _plant_manifest(),
            assets,
            temp_dir=tempfile.gettempdir(),
            filename_prefix="plant_doctor",
        )

        db_path = Path(tempfile.gettempdir()) / f"plant_doctor_run_{uuid.uuid4().hex}.sqlite"
        started = start_run(
            AGENT,
            media=media,
            db_path=str(db_path),
            auto_finalize=_env_bool("PLANT_DOCTOR_AUTO_APPROVE", False),
            auto_finalize_reviewer="hosted_trial",
        )
        if started.get("final_output") is not None:
            started["final_output"] = build_plant_care_report(
                started, allow_demo_data=allow_demo_data, manifest=_plant_manifest()
            )
            _write_latest_report(started["final_output"])
        else:
            started["drafted_output"] = build_plant_care_report(
                started, allow_demo_data=allow_demo_data, manifest=_plant_manifest()
            )
        output = started.get("final_output") or started.get("drafted_output") or {}
        care_report = output.get("care_report", {}) if isinstance(output, dict) else {}
        _log_run_result(
            client_session_id,
            status=started.get("status", ""),
            thread_id=started.get("thread_id", ""),
            completed=bool(output.get("completed")) if isinstance(output, dict) else False,
            failure_count=len(care_report.get("failures", []) or []),
            report_status=care_report.get("status", ""),
        )
        return JSONResponse(started)

    @app.post("/api/decision")
    async def decision(request: Request, payload: Dict[str, Any]) -> JSONResponse:
        allow_demo_data = bool(payload.get("allow_demo_data", False))
        final = resume_run(
            AGENT,
            thread_id=payload["thread_id"],
            decision={
                "decision": payload.get("decision", "approve"),
                "edits": payload.get("edits", {}),
                "note": payload.get("note", ""),
                "reviewer": payload.get("reviewer", "ui"),
            },
            db_path=payload["db_path"],
        )
        final["final_output"] = build_plant_care_report(
            final, allow_demo_data=allow_demo_data, manifest=_plant_manifest()
        )
        _write_latest_report(final["final_output"])
        _log_run_result(
            session_id_from_request(request),
            event="decision",
            status=final.get("status", ""),
            thread_id=final.get("thread_id", payload.get("thread_id", "")),
            completed=bool(final.get("final_output", {}).get("completed")),
            decision=payload.get("decision", "approve"),
            report_status=final.get("final_output", {}).get("care_report", {}).get("status", ""),
        )
        return JSONResponse(final)

    @app.post("/api/tts")
    async def tts(payload: Dict[str, Any]) -> JSONResponse:
        from core.adapters.base import ActionRequest
        from core.voice_adapter import ElevenLabsVoiceAdapter

        provider = None
        if not os.environ.get("ELEVENLABS_API_KEY"):
            from core.kids_voice_assessment.providers import MockVoiceProvider

            provider = MockVoiceProvider()

        adapter = ElevenLabsVoiceAdapter(provider=provider)
        result = adapter.act(
            ActionRequest(
                step_id="care_plan",
                action="speak",
                payload={"text": payload.get("text", "")},
            )
        )
        return JSONResponse(
            {
                "ok": result.ok,
                "audio_uri": result.data.get("audio_uri"),
                "detail": result.detail,
            }
        )

    if WEB.exists():
        app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
    return app


app = create_app()


@lru_cache(maxsize=1)
def _plant_manifest():
    return build_agent_manifest(AGENT)


@lru_cache(maxsize=1)
def _plant_step_ids() -> Dict[str, Any]:
    """Derive compiled step IDs from manifest media requirements."""
    vision: Dict[str, str] = {}
    voice = ""
    for requirement in _plant_manifest().media_requirements:
        if "whole_plant_photo" in requirement.evidence_refs:
            vision["whole_plant_photo"] = requirement.step_id
        if "closeup_photo" in requirement.evidence_refs:
            vision["closeup_photo"] = requirement.step_id
        if requirement.modality == "voice":
            voice = requirement.step_id
    return {"vision": vision, "voice": voice}


def _get_elevenlabs_conversation_token(agent_id: str, api_key: str) -> str:
    query = urllib.parse.urlencode({"agent_id": agent_id})
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/convai/conversation/token?{query}",
        headers={"xi-api-key": api_key},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
        body = json.loads(response.read().decode("utf-8"))
    token = body.get("token", "")
    if not token:
        raise RuntimeError("response did not include a token")
    return token


def _elevenlabs_client_tools() -> Dict[str, str]:
    return build_client_tool_summary(_plant_manifest(), _plant_tool_names())


def _elevenlabs_tool_configs() -> list[Dict[str, Any]]:
    return build_client_tool_configs(
        _plant_manifest(),
        _plant_tool_names(),
        record_topics=_PLANT_RECORD_TOPICS,
        structured_properties=_PLANT_STRUCTURED_PROPERTIES,
    )


def _elevenlabs_setup_payload() -> Dict[str, Any]:
    return {
        "agent_name": "SOPilot Plant Doctor",
        "agent_prompt": _agent_dynamic_variables()["plant_doctor_instructions"],
        "first_message": "Hi, I am your Plant Doctor. First, please show me the whole plant.",
        "client_tools": _elevenlabs_tool_configs(),
        "required_environment": [
            "OPENAI_API_KEY",
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_PLANT_DOCTOR_AGENT_ID or ELEVENLABS_AGENT_ID",
        ],
        "api_reference": {
            "create_agent": "https://api.elevenlabs.io/v1/convai/agents/create",
            "create_tool": "https://api.elevenlabs.io/v1/convai/tools",
        },
    }


def _agent_dynamic_variables() -> Dict[str, str]:
    return {
        "plant_doctor_instructions": build_guided_instructions(
            _plant_manifest(),
            _plant_tool_names(),
            record_topics=_PLANT_RECORD_TOPICS,
            domain_rules=(
                "The recent changes or pests question is required because recent repotting, "
                "moves, fertilizer, cold drafts, missed watering, and pests often explain "
                "the actual root cause."
            ),
            failure_policy=(
                "If submitPlantDoctorRun reports failure, use its reason and next_steps exactly. "
                "If it says care_habits_received or do_not_reask_care_habits, do not ask the "
                "care routine again; ask only for the missing or low-confidence photo retry. "
                "When retry_photo_fields includes whole_plant_photo, ask for the whole plant "
                "again and call captureWholePlantPhoto. When it includes closeup_photo, ask "
                "for the affected-leaf close-up again and call captureCloseupPhoto. After the "
                "retry capture, call submitPlantDoctorRun again using the care answers already recorded."
            ),
            final_policy=(
                "If submission succeeds and returns final_spoken_summary, speak that summary "
                "completely and do not cut off the final sentence. If only report_preview is "
                "returned, say one brief expert summary covering the issue, likely root cause, "
                "and top care tip, then tell the user the detailed report is shown on screen. "
                "After that final message, stop asking questions; the browser will close the "
                "voice session after speech finishes."
            ),
        )
    }


@lru_cache(maxsize=1)
def _plant_tool_names():
    return build_guided_tool_names(
        _plant_manifest(),
        state_tool="getPlantDoctorState",
        submit_tool="submitPlantDoctorRun",
        record_answer_tool="recordCareHabitAnswer",
        capture_tool_overrides=_PLANT_CAPTURE_TOOL_OVERRIDES,
    )


def _configuration_failure(reason: str, next_step: str) -> Dict[str, Any]:
    return {
        "summary": "Plant Doctor could not produce a reliable care report.",
        "completed": False,
        "care_report": {
            "status": "incomplete",
            "failures": [{"field": "configuration", "reason": reason}],
            "next_steps": [next_step],
        },
        "_meta": {"status": "failed", "source": "plant_doctor_report"},
        "_evidence": [],
    }


def _web_config_js() -> str:
    return "\n".join(
        [
            f"window.PLANT_DOCTOR_API_URL = {json.dumps(os.environ.get('PLANT_DOCTOR_API_URL', ''))};",
            f"window.PLANT_DOCTOR_APP_TOKEN = {json.dumps(os.environ.get('PLANT_DOCTOR_APP_TOKEN', ''))};",
            "window.PLANT_DOCTOR_AUTH_REQUIRED = "
            f"{json.dumps(bool(os.environ.get('PLANT_DOCTOR_TRIAL_CODE', '')))};",
            "",
        ]
    )


def _log_guide_session(session_id: str, **fields: Any) -> None:
    log_session_event(
        "voice_session_config",
        app="plant_doctor",
        session_id=session_id,
        **fields,
    )


def _log_run_result(session_id: str, event: str = "run", **fields: Any) -> None:
    log_session_event(
        event,
        app="plant_doctor",
        session_id=session_id,
        **fields,
    )


def _parse_json_object(raw: str) -> Dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_latest_report(report: Dict[str, Any]) -> None:
    if _env_bool("PLANT_DOCTOR_SKIP_LOCAL_REPORT_WRITE", False):
        return
    out_path = AGENT / "sample_outputs" / "latest_run.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_text(json.dumps(report, indent=2))
    except OSError:
        return


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
