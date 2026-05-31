import json
from pathlib import Path

import pytest
import yaml

from core.kids_voice_assessment.feedback import contains_banned_words
from core.kids_voice_assessment.hinglish_nlp import (
    analyze_tokens,
    compare_reference_to_spoken_tokens,
    normalize_hinglish_text,
)
from core.kids_voice_assessment.models import (
    AlignmentState,
    AudioState,
    PhonemeState,
    TranscriptState,
)
from core.kids_voice_assessment.providers import ElevenLabsVoiceProvider, MockVoiceProvider
from core.kids_voice_assessment.scoring import calculate_scores
from core.kids_voice_assessment.service import KidsVoiceAssessmentService
from sopilot.config import load_agent_config


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "kids_voice_assessment_agent"


def _service() -> KidsVoiceAssessmentService:
    service = KidsVoiceAssessmentService(example_dir=EXAMPLE, provider=MockVoiceProvider())
    service.config["runtime"]["allow_fixture_provider_for_local_demo"] = True
    return service


def test_config_loads_and_validates():
    config = load_agent_config(EXAMPLE)
    raw_config = yaml.safe_load((EXAMPLE / "agent_config.yaml").read_text())
    assert config.name == "kids_voice_assessment_agent"
    assert config.model.compiler.use_llm is False
    assert raw_config["runtime"]["production_requires_real_stt_alignment"] is True
    assert raw_config["runtime"]["allow_fixture_provider_for_local_demo"] is False
    raw = json.loads((EXAMPLE / "prompts" / "hinglish_level_1.json").read_text())
    assert raw["prompts"][0]["allowed_variants"]["school"] == ["iskool"]


def test_mock_voice_provider_returns_deterministic_transcript():
    provider = MockVoiceProvider()
    audio = AudioState(
        recording_id="rec1",
        volume_score=0.8,
        noise_score=0.8,
        vad_speech_detected=True,
        quality_status="ok",
    )
    result = provider.transcribe_audio(
        audio,
        {"reference_text": "The red ball is under the table."},
    )
    assert result.raw_transcript == "the red ball is under table"
    assert result.word_timestamps


def test_default_service_uses_real_elevenlabs_provider_not_fixture(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    service = KidsVoiceAssessmentService(example_dir=EXAMPLE)
    assert isinstance(service.provider, ElevenLabsVoiceProvider)
    assert getattr(service.provider, "is_fixture") is False
    session = service.create_session(
        child_id="child_real_default",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        service.run_session(session.session_id)


def test_elevenlabs_provider_shapes_real_stt_and_alignment_requests(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    audio_path = tmp_path / "child.wav"
    audio_path.write_bytes(b"fake-wav")
    calls = []

    class CaptureElevenLabsProvider(ElevenLabsVoiceProvider):
        def _post_multipart(self, path, *, file_field, file_name, file_bytes, fields):
            calls.append(
                {
                    "path": path,
                    "file_field": file_field,
                    "file_name": file_name,
                    "file_bytes": file_bytes,
                    "fields": fields,
                }
            )
            if path == "/v1/speech-to-text":
                return {
                    "text": "hello",
                    "language_code": "en",
                    "language_probability": 0.94,
                    "words": [
                        {
                            "text": "hello",
                            "start": 0.1,
                            "end": 0.52,
                            "type": "word",
                            "confidence": 0.93,
                        }
                    ],
                }
            return {
                "words": [
                    {"text": "hello", "start": 0.1, "end": 0.52, "loss": 0.04}
                ],
                "characters": [],
                "loss": 0.04,
            }

    provider = CaptureElevenLabsProvider(external_provider_allowed=True)
    audio = AudioState(
        recording_id="rec_real",
        raw_audio_uri=str(audio_path),
        volume_score=0.8,
        noise_score=0.8,
        vad_speech_detected=True,
        quality_status="ok",
    )
    transcript = provider.transcribe_audio(
        audio,
        {
            "keyterms": ["hello"],
            "language_hint": "en",
            "use_language_detection": False,
        },
    )
    alignment = provider.forced_align(audio, "hello", {})

    assert [call["path"] for call in calls] == [
        "/v1/speech-to-text",
        "/v1/forced-alignment",
    ]
    assert calls[0]["file_field"] == "file"
    assert calls[0]["fields"]["model_id"] == "scribe_v2"
    assert calls[0]["fields"]["language_code"] == "en"
    assert calls[0]["fields"]["keyterms"] == ["hello"]
    assert calls[1]["fields"]["text"] == "hello"
    assert transcript.metadata.provider == "elevenlabs"
    assert transcript.word_timestamps[0].start_ms == 100
    assert alignment.metadata.provider == "elevenlabs"
    assert alignment.metadata.confidence == 0.96


def test_low_quality_audio_triggers_retry_without_scoring():
    service = _service()
    session = service.create_session(
        child_id="child_low_audio",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(
        session.session_id,
        volume_score=0.18,
        noise_score=0.62,
        vad_speech_detected=False,
    )
    session = service.run_session(session.session_id)
    assert session.status == "needs_retry"
    assert session.audio.quality_status == "retry"
    assert "Mic ko thoda paas" in session.feedback.child_feedback
    assert session.scores.overall_score == 0


def test_age_segments_select_different_assessment_batteries():
    service = _service()
    age3 = service.create_session(child_id="age3", age_years=3)
    age8 = service.create_session(child_id="age8", age_years=8)
    assert age3.battery_id == "bolo_age_3_4_foundation"
    assert age8.battery_id == "bolo_age_7_8_code_switch_story"
    assert age3.selected_prompt_ids != age8.selected_prompt_ids
    assert age3.prompt_id.startswith("age3_4")
    assert age8.prompt_id.startswith("age7_8")


def test_prompts_for_age_do_not_mix_three_and_eight_year_old_tasks():
    service = _service()
    age3_prompts = service.list_prompts_for_age(3)
    age8_prompts = service.list_prompts_for_age(8)
    assert age3_prompts and age8_prompts
    assert all(p.age_min <= 3 <= p.age_max for p in age3_prompts if p.age_min)
    assert all(p.age_min <= 8 <= p.age_max for p in age8_prompts if p.age_min)
    assert {p.prompt_id for p in age3_prompts}.isdisjoint({p.prompt_id for p in age8_prompts})


def test_battery_run_aggregates_multiple_age_appropriate_tasks():
    service = _service()
    session = service.create_session(child_id="battery_age8", age_years=8)
    service.attach_audio(session.session_id)
    session = service.run_battery_session(
        session.session_id,
        task_inputs={
            "age7_8_code_switch_lunch": {
                "mock_transcript": "I went school phir lunch khaya"
            },
            "age7_8_story_sequence_space": {
                "mock_transcript": "pehle rocket moon gaya phir robot happy hua"
            },
            "age7_8_memory_metro": {
                "mock_transcript": "the metro stopped then my dost found blue ticket"
            },
        },
    )
    assert len(session.battery_results) == len(session.selected_prompt_ids) == 3
    assert {task.prompt_id for task in session.battery_results} == set(session.selected_prompt_ids)
    report = service.get_full_report(session.session_id)
    assert len(report["task_results"]) == 3
    assert report["assessment_battery"]["age_years"] == 8
    assert report["assessment_battery"]["selected_prompt_ids"] == session.selected_prompt_ids
    assert "code_switch_control" in report["domains"]
    assert "narrative_reasoning" in report["domains"]
    assert "working_memory" in report["domains"]
    assert report["domains"]["working_memory"]["task_count"] >= 2
    assert report["exercises"]
    parent = service.get_result(session.session_id, viewer_role="parent")
    assert len(parent["task_results"]) == 3
    assert "age-appropriate voice tasks" in parent["report"]


def test_three_year_battery_runs_short_foundation_tasks_only():
    service = _service()
    session = service.create_session(child_id="battery_age3", age_years=3)
    assert all(prompt_id.startswith("age3_4") for prompt_id in session.selected_prompt_ids)
    service.attach_audio(session.session_id)
    session = service.run_session(session.session_id)
    assert len(session.battery_results) == 3
    assert all(task.prompt_id.startswith("age3_4") for task in session.battery_results)
    assert all(len(task.prompt_text.split()) <= 7 for task in session.battery_results)
    report = service.get_full_report(session.session_id)
    assert "receptive_language" in report["domains"]
    assert "attention" in report["domains"]
    assert "vocabulary" in report["domains"]


def test_hinglish_normalization_works_for_sample_phrases():
    assert normalize_hinglish_text("Mera red ball table ke under hai!") == (
        "mera red ball table ke under hai"
    )
    assert normalize_hinglish_text("आज I read a story") == "आज i read a story"


def test_code_switch_token_tagging_for_mixed_sentence():
    state = analyze_tokens(
        "Aaj I read a story",
        "Aaj I read a story",
        {"story": ["kahani"]},
    )
    spoken_tags = [(t.normalized_text, t.language, t.script) for t in state.spoken_tokens]
    assert ("aaj", "hi", "latin") in spoken_tags
    assert ("i", "en", "latin") in spoken_tags
    assert state.code_switch_events


def test_allowed_variants_map_iskool_only_when_configured():
    no_variant = compare_reference_to_spoken_tokens(
        ["mera", "school", "bag"],
        ["mera", "iskool", "bag"],
        allowed_variants={},
        code_switch_policy="allow_common_hinglish",
    )
    with_variant = compare_reference_to_spoken_tokens(
        ["mera", "school", "bag"],
        ["mera", "iskool", "bag"],
        allowed_variants={"school": ["iskool"]},
        code_switch_policy="allow_common_hinglish",
    )
    assert [item.status for item in no_variant] == ["matched", "substituted", "matched"]
    assert [item.status for item in with_variant] == ["matched", "variant", "matched"]


def test_strict_reading_penalizes_more_than_expressive_speaking():
    alignment = compare_reference_to_spoken_tokens(
        ["the", "red", "ball", "is", "under", "the", "table"],
        ["mera", "red", "ball", "table", "ke", "under", "hai"],
        assessment_mode="strict_reading",
    )
    alignment_state = AlignmentState(
        word_alignment=alignment,
        matched_words=[w.reference for w in alignment if w.status == "matched" and w.reference],
        missed_words=[w.reference for w in alignment if w.status == "missed" and w.reference],
        inserted_words=[w.spoken for w in alignment if w.status == "inserted" and w.spoken],
        substituted_words=[
            {"reference": w.reference or "", "spoken": w.spoken or ""}
            for w in alignment
            if w.status == "substituted"
        ],
    )
    audio = AudioState(volume_score=0.85, noise_score=0.85, vad_speech_detected=True)
    transcript = TranscriptState(language_probability=0.82)
    phonemes = PhonemeState(phoneme_confidence=0.74)
    strict = calculate_scores(
        alignment_state,
        audio,
        transcript,
        phonemes,
        assessment_mode="strict_reading",
    )
    expressive = calculate_scores(
        alignment_state,
        audio,
        transcript,
        phonemes,
        assessment_mode="expressive_speaking",
    )
    assert strict.overall_score < expressive.overall_score


def test_feedback_generator_avoids_banned_words():
    service = _service()
    session = service.create_session(
        child_id="child_feedback",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    session = service.run_session(session.session_id)
    banned = service.config["feedback"]["avoid_words"]
    assert not contains_banned_words(session.feedback.child_feedback, banned)
    assert not contains_banned_words(session.feedback.adult_feedback, banned)


def test_child_feedback_hides_raw_scores():
    service = _service()
    session = service.create_session(
        child_id="child_payload",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    service.run_session(session.session_id)
    child = service.get_result(session.session_id, viewer_role="child")
    assert child["show_raw_scores"] is False
    assert "scores" not in child


def test_parent_report_includes_evidence_and_uncertainty():
    service = _service()
    session = service.create_session(
        child_id="child_parent",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    service.run_session(session.session_id)
    report = service.get_result(session.session_id, viewer_role="parent")
    assert "evidence" in report and report["evidence"]
    assert "uncertainty" in report
    assert "scores" in report


def test_full_report_includes_insights_and_exercises_without_iq_claim():
    service = _service()
    session = service.create_session(
        child_id="child_full_report",
        age_years=8,
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    service.run_session(session.session_id)
    report = service.get_full_report(session.session_id)
    assert report["insights"]
    assert report["exercises"]
    assert "not an IQ test" in report["disclaimer"]
    assert "battery_id" in report
    assert report["assessment_battery"]["task_count"] == 3


def test_deletion_service_marks_recording_deleted():
    service = _service()
    session = service.create_session(
        child_id="child_delete",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    recording = service.attach_audio(session.session_id)
    deleted = service.delete_recording(recording.recording_id)
    assert deleted.deleted is True
    assert deleted.raw_audio_uri is None
    assert service.sessions[session.session_id].privacy.deletion_requested is True


def test_human_review_triggers_on_low_confidence_alignment():
    service = _service()
    session = service.create_session(
        child_id="child_review",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    session = service.run_session(session.session_id, mock_transcript="zzz yyy")
    assert session.review.needs_human_review is True
    assert "low_alignment_confidence" in session.review.review_reason
    assert f"review_{session.session_id}" in service.review_cases


def test_production_blocks_fixture_provider_when_local_demo_is_disabled():
    service = _service()
    service.config["runtime"]["allow_fixture_provider_for_local_demo"] = False
    session = service.create_session(
        child_id="child_prod_gate",
        prompt_id="indian_english_l1_001",
        consent_status="verified",
    )
    service.attach_audio(session.session_id)
    with pytest.raises(RuntimeError, match="requires real STT/alignment"):
        service.run_session(session.session_id)


def test_output_schema_validates_sample_outputs():
    schema = json.loads((EXAMPLE / "output_schema.json").read_text())
    required = set(schema["required"])
    for path in (EXAMPLE / "sample_outputs").glob("*_report.json"):
        sample = json.loads(path.read_text())
        assert required.issubset(sample.keys()), path.name
        for key in sample:
            if key in {"_meta", "_evidence"}:
                continue
            assert key in schema["properties"], f"{path.name}: {key}"
