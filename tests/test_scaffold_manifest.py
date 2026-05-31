"""Reusable scaffold manifest and provider policy helpers."""

from pathlib import Path

import pytest

from sopilot.config import load_agent_config
from sopilot.cli import main
from sopilot.runner import _build_adapters, start_run
from sopilot.scaffold import ProviderConfigurationError, build_agent_manifest

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def test_manifest_exposes_media_questions_reviews_and_provider_status(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    manifest = build_agent_manifest(AGENT)

    media_refs = [item.evidence_refs for item in manifest.media_requirements]
    assert ["whole_plant_photo"] in media_refs
    assert ["closeup_photo"] in media_refs
    media_by_modality = {item.modality: item for item in manifest.media_requirements}
    voice = media_by_modality["voice"]
    assert voice.evidence_refs == ["care_habits_audio"]
    assert len(voice.drilldown_questions) == 4
    assert manifest.review_points[0]["trigger"] == "final_submit"
    assert {status.modality for status in manifest.adapters} == {"vision", "voice"}
    assert all(status.fallback_to_stub for status in manifest.adapters)


def test_live_required_adapter_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = load_agent_config(AGENT)
    config.runtime.require_live_adapters = True

    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        _build_adapters(config)


def test_start_run_can_auto_finalize_hitl(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    result = start_run(AGENT, media={}, db_path=db, auto_finalize=True)
    assert result["status"] == "completed"
    assert result["final_output"]["completed"] is True
    assert result["human_overrides"][0]["reviewer"] == "auto"


def test_manifest_cli_prints_app_facing_metadata(capsys):
    assert main(["manifest", str(AGENT)]) == 0
    out = capsys.readouterr().out
    assert "media_requirements" in out
    assert "care_habits_audio" in out
