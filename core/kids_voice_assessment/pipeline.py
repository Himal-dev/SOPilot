"""Deterministic Kids Voice Assessment pipeline.

Each method maps to a product/SOP node. The class can be used directly by tests
and services, while ``graph.py`` exposes the same node names through LangGraph.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.kids_voice_assessment.feedback import (
    adult_report_payload,
    child_result_payload,
    generate_feedback,
)
from core.kids_voice_assessment.hinglish_nlp import (
    analyze_tokens,
    generate_code_switch_variants,
)
from core.kids_voice_assessment.models import (
    AssessmentPrompt,
    AudioState,
    AuditEvent,
    KidsVoiceAssessmentRunState,
    ModelMetadata,
)
from core.kids_voice_assessment.phonemes import analyze_pronunciation
from core.kids_voice_assessment.providers import MockVoiceProvider, VoiceProvider
from core.kids_voice_assessment.scoring import DEFAULT_WEIGHTS, calculate_scores


DEFAULT_THRESHOLDS = {
    "min_audio_quality": 0.55,
    "min_stt_confidence": 0.55,
    "min_alignment_confidence": 0.50,
    "min_phoneme_confidence": 0.50,
    "human_review_below_confidence": 0.45,
}


class KidsVoiceAssessmentPipeline:
    """Production-shaped, mock-friendly assessment orchestrator."""

    def __init__(
        self,
        *,
        provider: Optional[VoiceProvider] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.provider = provider or MockVoiceProvider()
        self.config = config or {}

    def run(
        self,
        state: KidsVoiceAssessmentRunState,
        *,
        mock_transcript: Optional[str] = None,
    ) -> KidsVoiceAssessmentRunState:
        self._assert_real_provider_if_required()
        state = self.load_assessment_config(state)
        state = self.present_prompt(state)
        if not state.privacy.consent_verified:
            state.status = "consent_required"
            state.assessment.current_step = "consent_required"
            state.feedback.child_feedback = (
                "Parent ya teacher se permission ke baad practice start karte hain."
            )
            return state

        state = self.maybe_generate_prompt_audio(state)
        state = self.capture_audio(state)
        state = self.validate_audio_quality(state)
        if state.audio.quality_status != "ok":
            if state.audio.retry_count < self._max_retries():
                state.status = "needs_retry"
                state.feedback = generate_feedback(
                    state.scores,
                    state.alignment,
                    state.phonemes,
                    audio_quality_ok=False,
                    tone=self._feedback_tone(),
                    banned_words=self._banned_words(),
                    child_templates=self._child_templates(),
                )
                state.final_child_result = child_result_payload(state.feedback, state.scores)
                return state
            state.review.needs_human_review = True
            state.review.review_reason.append("poor_audio_after_retries")
            state.status = "needs_human_review"
            state.feedback = generate_feedback(
                state.scores,
                state.alignment,
                state.phonemes,
                audio_quality_ok=False,
                tone=self._feedback_tone(),
                banned_words=self._banned_words(),
                child_templates=self._child_templates(),
            )
            return self.return_child_result(state)

        state = self.maybe_clean_audio(state)
        state = self.transcribe_audio(state, mock_transcript=mock_transcript)
        state = self.normalize_hinglish(state)
        state = self.generate_reference_variants(state)
        state = self.align_to_reference(state)
        state = self.run_phoneme_analysis(state)
        state = self.calculate_scores(state)
        state = self.generate_feedback(state)
        state = self.persist_assessment(state)
        state = self.maybe_trigger_human_review(state)
        if state.assessment.ui_mode == "child":
            return self.return_child_result(state)
        return self.return_adult_report(state)

    # -- SOP/product nodes ----------------------------------------------------

    def load_assessment_config(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "load_assessment_config"
        if state.prompt:
            prompt = state.prompt
            state.assessment.prompt_id = prompt.prompt_id
            state.assessment.prompt_type = prompt.prompt_type
            state.assessment.reference_text = prompt.text
            state.assessment.reference_language = prompt.language_mode
            state.assessment.expected_script = prompt.script
            state.assessment.assessment_mode = prompt.assessment_mode
        state.add_evidence(
            "config",
            f"Loaded assessment config for {state.assessment.prompt_id}",
        )
        return state

    def present_prompt(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "present_prompt"
        display = state.prompt.display_text if state.prompt else state.assessment.reference_text
        state.add_evidence("ui", f"Presented child prompt: {display}")
        return state

    def maybe_generate_prompt_audio(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "maybe_generate_prompt_audio"
        if not self._tts_enabled():
            return state
        prompt_text = (
            state.prompt.audio_prompt_text if state.prompt else state.assessment.reference_text
        )
        result = self.provider.synthesize_speech(
            prompt_text,
            {"voice_profile": "friendly_indian_english"},
        )
        state.add_evidence("tts", "Generated prompt playback audio", result.audio_uri)
        return state

    def capture_audio(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "capture_audio"
        if not state.audio.recording_id:
            state.audio.recording_id = f"rec_{state.assessment.session_id or 'local'}"
        if not state.audio.raw_audio_uri:
            state.audio.raw_audio_uri = f"mock://recordings/{state.audio.recording_id}"
        state.add_evidence(
            "audio",
            f"Attached recording {state.audio.recording_id}",
            state.audio.raw_audio_uri,
        )
        return state

    def validate_audio_quality(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "validate_audio_quality"
        quality = (state.audio.volume_score + state.audio.noise_score) / 2
        if not state.audio.vad_speech_detected:
            state.audio.quality_status = "retry"
        elif quality < self._threshold("min_audio_quality"):
            state.audio.quality_status = "retry"
        else:
            state.audio.quality_status = "ok"
        state.add_evidence(
            "audio_quality",
            (
                f"Audio quality {state.audio.quality_status}: volume="
                f"{state.audio.volume_score:.2f}, noise={state.audio.noise_score:.2f}"
            ),
        )
        return state

    def maybe_clean_audio(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "maybe_clean_audio"
        isolation_cfg = self.config.get("elevenlabs", {}).get("audio_isolation", {})
        should_clean = bool(isolation_cfg.get("enabled", False)) and (
            state.audio.noise_score < float(isolation_cfg.get("only_if_noise_score_below", 0.72))
        )
        if not should_clean:
            return state
        result = self.provider.isolate_voice(state.audio, {})
        state.audio.cleaned_audio_uri = result.cleaned_audio_uri
        state.add_evidence("audio_isolation", "Cleaned recording for noisy input", result.cleaned_audio_uri)
        return state

    def transcribe_audio(
        self,
        state: KidsVoiceAssessmentRunState,
        *,
        mock_transcript: Optional[str] = None,
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "transcribe_audio"
        state.transcript = self.provider.transcribe_audio(
            state.audio,
            {
                "reference_text": state.assessment.reference_text,
                "mock_transcript": mock_transcript,
                "keyterms": _target_terms(state.prompt),
                "language_hint": state.assessment.reference_language,
            },
        )
        state.add_evidence(
            "transcript",
            f"Transcript: {state.transcript.raw_transcript}",
            metadata=state.transcript.metadata.model_dump(),
        )
        return state

    def normalize_hinglish(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "normalize_hinglish"
        variants = state.prompt.allowed_variants if state.prompt else {}
        state.nlp = analyze_tokens(
            state.assessment.reference_text,
            state.transcript.raw_transcript,
            variants,
        )
        state.transcript.detected_code_switches = state.nlp.code_switch_events
        state.add_evidence(
            "hinglish_nlp",
            "Normalized reference and spoken text with token language tags",
            metadata=state.nlp.metadata.model_dump(),
        )
        return state

    def generate_reference_variants(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "generate_reference_variants"
        variants = generate_code_switch_variants(
            state.assessment.reference_text,
            state.nlp.allowed_reference_variants,
        )
        state.add_evidence(
            "reference_variants",
            f"Generated {len(variants)} prompt-scoped accepted variant(s)",
            variants=variants,
        )
        return state

    def align_to_reference(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "align_to_reference"
        state.alignment = self.provider.forced_align(
            state.audio,
            state.assessment.reference_text,
            {
                "spoken_text": state.transcript.raw_transcript,
                "allowed_variants": state.nlp.allowed_reference_variants,
                "code_switch_policy": state.assessment.code_switch_policy,
                "assessment_mode": state.assessment.assessment_mode,
            },
        )
        state.add_evidence(
            "alignment",
            "Aligned spoken tokens to reference text",
            metadata=state.alignment.metadata.model_dump(),
        )
        return state

    def run_phoneme_analysis(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "run_phoneme_analysis"
        state.phonemes = analyze_pronunciation(
            state.assessment.reference_text,
            state.transcript.raw_transcript,
            target_phonemes=state.prompt.target_phonemes if state.prompt else [],
            accent_tolerance_profile=self._accent_profile(),
        )
        state.add_evidence(
            "phonemes",
            "Generated fallback phoneme comparison with accent tolerance",
            metadata=state.phonemes.metadata.model_dump(),
        )
        return state

    def calculate_scores(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "calculate_scores"
        state.scores = calculate_scores(
            state.alignment,
            state.audio,
            state.transcript,
            state.phonemes,
            assessment_mode=state.assessment.assessment_mode,
            weights=self.config.get("scoring", {}).get("weights", DEFAULT_WEIGHTS),
        )
        state.add_evidence(
            "scores",
            "Calculated gentle multi-dimensional scores",
            metadata=state.scores.metadata.model_dump(),
        )
        return state

    def generate_feedback(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "generate_feedback"
        state.feedback = generate_feedback(
            state.scores,
            state.alignment,
            state.phonemes,
            audio_quality_ok=state.audio.quality_status == "ok",
            tone=self._feedback_tone(),
            banned_words=self._banned_words(),
            child_templates=self._child_templates(),
        )
        state.add_evidence(
            "feedback",
            "Generated separate child and adult feedback",
            metadata=state.feedback.metadata.model_dump(),
        )
        return state

    def persist_assessment(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "persist_assessment"
        state.status = "completed"
        state.audit_events.append(
            AuditEvent(
                event_id=f"audit_{len(state.audit_events) + 1:04d}",
                session_id=state.assessment.session_id,
                event_type="assessment_persisted",
                detail={"prompt_id": state.assessment.prompt_id},
            )
        )
        state.add_evidence("persistence", "Persisted structured assessment result")
        return state

    def maybe_trigger_human_review(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "maybe_trigger_human_review"
        reasons: List[str] = []
        if state.transcript.metadata.confidence < self._threshold("min_stt_confidence"):
            reasons.append("low_model_confidence")
        if state.alignment.metadata.confidence < self._threshold("min_alignment_confidence"):
            reasons.append("low_alignment_confidence")
        if state.phonemes.phoneme_confidence < self._threshold("min_phoneme_confidence"):
            reasons.append("low_phoneme_confidence")
        if state.scores.confidence_score < self._threshold("human_review_below_confidence"):
            reasons.append("low_model_confidence")
        if state.scores.overall_score < 0.40 and state.audio.quality_status == "ok":
            reasons.append("sensitive_developmental_signal")
        if reasons:
            state.review.needs_human_review = True
            state.review.review_reason = sorted(set(reasons))
            state.status = "needs_human_review"
            state.feedback.should_suppress_child_feedback = True
        state.add_evidence(
            "human_review",
            "Human review routing evaluated",
            reasons=state.review.review_reason,
            needs_review=state.review.needs_human_review,
        )
        return state

    def return_child_result(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "return_child_result"
        state.final_child_result = child_result_payload(state.feedback, state.scores)
        return state

    def return_adult_report(
        self, state: KidsVoiceAssessmentRunState
    ) -> KidsVoiceAssessmentRunState:
        state.assessment.current_step = "return_adult_report"
        state.final_adult_report = adult_report_payload(
            state.feedback,
            state.scores,
            state.alignment,
            evidence=[e.model_dump() for e in state.evidence],
        )
        return state

    # -- config helpers -------------------------------------------------------

    def _threshold(self, key: str) -> float:
        return float(
            self.config.get("scoring", {})
            .get("thresholds", {})
            .get(key, DEFAULT_THRESHOLDS[key])
        )

    def _max_retries(self) -> int:
        return int(self.config.get("assessment", {}).get("retries", {}).get("max_retries", 2))

    def _feedback_tone(self) -> str:
        return self.config.get("feedback", {}).get("default_child_tone", "hinglish_warm")

    def _banned_words(self) -> List[str]:
        return list(self.config.get("feedback", {}).get("avoid_words", [])) or [
            "wrong",
            "bad",
            "poor",
            "failed",
            "disorder",
            "abnormal",
        ]

    def _child_templates(self) -> Dict[str, str]:
        return dict(self.config.get("feedback", {}).get("child_templates", {}))

    def _accent_profile(self) -> str:
        return self.config.get("phonemes", {}).get(
            "accent_tolerance_profile", "indian_english_default"
        )

    def _tts_enabled(self) -> bool:
        eleven = self.config.get("elevenlabs", {})
        return bool(eleven.get("enabled", False) and eleven.get("tts", {}).get("enabled", False))

    def _assert_real_provider_if_required(self) -> None:
        runtime = self.config.get("runtime", {})
        assessment = self.config.get("assessment", {})
        require_real = bool(
            runtime.get("production_requires_real_stt_alignment")
            or assessment.get("require_real_voice_provider")
        )
        allow_fixture = bool(runtime.get("allow_fixture_provider_for_local_demo", False))
        if require_real and getattr(self.provider, "is_fixture", False) and not allow_fixture:
            raise RuntimeError(
                "Production assessment requires real STT/alignment; fixture provider is disabled."
            )


def _target_terms(prompt: Optional[AssessmentPrompt]) -> List[str]:
    if prompt is None:
        return []
    return sorted({*prompt.target_words, *prompt.allowed_variants.keys()})
