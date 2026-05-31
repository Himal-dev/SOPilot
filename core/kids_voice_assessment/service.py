"""API-equivalent service functions for Kids Voice Assessment.

SOPilot does not currently ship an HTTP server, so these methods map one-to-one
to the requested REST routes and can be wrapped by FastAPI/Flask later.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from core.kids_voice_assessment.models import (
    AssessmentBattery,
    AssessmentPrompt,
    AssessmentSession,
    AssessmentTaskResult,
    AudioRecording,
    AudioState,
    ChildProfile,
    FeedbackState,
    HumanReviewCase,
    KidsVoiceAssessmentRunState,
    ModelMetadata,
    ReviewState,
    ScoreState,
    now_iso,
)
from core.kids_voice_assessment.pipeline import KidsVoiceAssessmentPipeline
from core.kids_voice_assessment.providers import (
    ElevenLabsVoiceProvider,
    MockVoiceProvider,
    VoiceProvider,
)
from core.kids_voice_assessment.reporting import build_full_report
from core.kids_voice_assessment.scoring import map_score_to_developmental_level


class KidsVoiceAssessmentService:
    """Small in-memory service for local demos and tests."""

    def __init__(
        self,
        *,
        example_dir: str | Path,
        provider: Optional[VoiceProvider] = None,
    ) -> None:
        self.example_dir = Path(example_dir)
        self.config = self._load_config()
        self.prompts = self._load_prompts()
        self.batteries = self._load_batteries()
        self.provider = provider or self._build_configured_provider()
        self.sessions: Dict[str, AssessmentSession] = {}
        self.recordings: Dict[str, AudioRecording] = {}
        self.review_cases: Dict[str, HumanReviewCase] = {}

    # POST /api/kids-voice/sessions
    def create_session(
        self,
        *,
        child_id: str,
        prompt_id: Optional[str] = None,
        age_years: Optional[int] = None,
        age_band: Optional[str] = None,
        grade_band: str = "",
        primary_language: str = "hinglish",
        secondary_language: str = "en",
        consent_status: str = "verified",
        viewer_role: str = "child",
        assessment_mode: Optional[str] = None,
        battery_id: Optional[str] = None,
    ) -> AssessmentSession:
        age_band = age_band or age_band_for(age_years)
        battery = self._select_battery(age_years, battery_id)
        prompt_id = prompt_id or (battery.prompt_ids[0] if battery else "")
        if not prompt_id:
            raise ValueError("prompt_id is required when no age-matched battery exists.")
        prompt = self.prompts[prompt_id]
        session_id = f"kva_{uuid.uuid4().hex[:12]}"
        session = AssessmentSession(
            session_id=session_id,
            child_id=child_id,
            prompt_id=prompt_id,
            age_years=age_years,
            battery_id=battery.battery_id if battery else battery_id,
            selected_prompt_ids=list(battery.prompt_ids if battery else [prompt_id]),
            assessment_domains=list(battery.domains if battery else prompt.assessment_domains),
            viewer_role=viewer_role,  # type: ignore[arg-type]
        )
        session.assessment.session_id = session_id
        session.assessment.child_id = child_id
        session.assessment.age_years = age_years
        session.assessment.age_band = age_band
        session.assessment.grade_band = grade_band
        session.assessment.primary_language = primary_language
        session.assessment.secondary_language = secondary_language
        session.assessment.prompt_id = prompt_id
        session.assessment.prompt_type = prompt.prompt_type
        session.assessment.reference_text = prompt.text
        session.assessment.reference_language = prompt.language_mode
        session.assessment.expected_script = prompt.script
        session.assessment.assessment_mode = assessment_mode or prompt.assessment_mode
        session.assessment.consent_status = consent_status
        session.assessment.ui_mode = viewer_role
        session.privacy.consent_verified = consent_status == "verified"
        session.privacy.store_raw_audio = bool(
            self.config.get("privacy", {}).get("store_raw_audio", True)
        )
        session.privacy.external_provider_allowed = bool(
            self.config.get("privacy", {}).get("external_provider_allowed", False)
        )
        session.status = "created"
        self.sessions[session_id] = session
        return session

    # GET /api/kids-voice/prompts
    def list_prompts(
        self,
        *,
        age_band: Optional[str] = None,
        language_mode: Optional[str] = None,
        assessment_mode: Optional[str] = None,
        skill: Optional[str] = None,
    ) -> List[AssessmentPrompt]:
        prompts: Iterable[AssessmentPrompt] = self.prompts.values()
        if age_band:
            prompts = [p for p in prompts if p.age_band == age_band]
        if language_mode:
            prompts = [p for p in prompts if p.language_mode == language_mode]
        if assessment_mode:
            prompts = [p for p in prompts if p.assessment_mode == assessment_mode]
        if skill:
            prompts = [p for p in prompts if skill in p.target_words or skill in p.target_phonemes]
        return list(prompts)

    def list_prompts_for_age(
        self,
        age_years: int,
        *,
        language_mode: Optional[str] = None,
        assessment_mode: Optional[str] = None,
    ) -> List[AssessmentPrompt]:
        prompts = [
            p
            for p in self.prompts.values()
            if _prompt_matches_age(p, age_years)
        ]
        if language_mode:
            prompts = [p for p in prompts if p.language_mode == language_mode]
        if assessment_mode:
            prompts = [p for p in prompts if p.assessment_mode == assessment_mode]
        return prompts

    # POST /api/kids-voice/sessions/{session_id}/audio
    def attach_audio(
        self,
        session_id: str,
        *,
        raw_audio_uri: str = "mock://recording",
        duration_ms: int = 2600,
        sample_rate: int = 16000,
        volume_score: float = 0.84,
        noise_score: float = 0.82,
        vad_speech_detected: bool = True,
        retry_count: int = 0,
    ) -> AudioRecording:
        session = self._session(session_id)
        recording_id = f"rec_{uuid.uuid4().hex[:10]}"
        recording = AudioRecording(
            recording_id=recording_id,
            session_id=session_id,
            raw_audio_uri=raw_audio_uri if session.privacy.store_raw_audio else None,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
        )
        self.recordings[recording_id] = recording
        session.audio = AudioState(
            recording_id=recording_id,
            raw_audio_uri=recording.raw_audio_uri,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            volume_score=volume_score,
            noise_score=noise_score,
            vad_speech_detected=vad_speech_detected,
            retry_count=retry_count,
        )
        session.updated_at = now_iso()
        return recording

    # POST /api/kids-voice/sessions/{session_id}/run
    def run_session(
        self,
        session_id: str,
        *,
        mock_transcript: Optional[str] = None,
        task_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> AssessmentSession:
        session = self._session(session_id)
        if _should_run_battery(session):
            if mock_transcript:
                task_inputs = dict(task_inputs or {})
                task_inputs.setdefault(session.prompt_id, {})[
                    "mock_transcript"
                ] = mock_transcript
            return self.run_battery_session(session_id, task_inputs=task_inputs)

        prompt, result, new_evidence = self._run_prompt(
            session,
            session.prompt_id,
            mock_transcript=mock_transcript,
        )
        self._apply_single_result(session, prompt, result, new_evidence)
        if session.review.needs_human_review:
            self.create_or_update_review(
                session_id,
                reason=session.review.review_reason,
                reviewer_notes="Auto-created by confidence/safety gate.",
            )
        return session

    def run_battery_session(
        self,
        session_id: str,
        *,
        task_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> AssessmentSession:
        """Run every age-selected prompt and aggregate one educational report."""

        session = self._session(session_id)
        prompt_ids = session.selected_prompt_ids or [session.prompt_id]
        session.battery_results = []
        task_inputs = task_inputs or {}

        for prompt_id in prompt_ids:
            inputs = _task_input(task_inputs, prompt_id)
            prompt, result, new_evidence = self._run_prompt(
                session,
                prompt_id,
                audio_overrides=inputs,
                mock_transcript=inputs.get("mock_transcript"),
            )
            session.evidence = result.evidence
            session.privacy = result.privacy
            session.battery_results.append(
                self._task_result_from_state(prompt, result, new_evidence)
            )

        self._apply_battery_aggregate(session)
        if session.review.needs_human_review:
            self.create_or_update_review(
                session_id,
                reason=session.review.review_reason,
                reviewer_notes="Auto-created by battery confidence/safety gate.",
            )
        return session

    # GET /api/kids-voice/sessions/{session_id}/result
    def get_result(self, session_id: str, *, viewer_role: str = "child") -> Dict[str, Any]:
        session = self._session(session_id)
        if viewer_role == "child":
            return {
                "session_id": session_id,
                "mode": "child",
                "feedback": session.feedback.child_feedback,
                "developmental_level": session.scores.developmental_level,
                "show_raw_scores": False,
                "suggested_practice": session.feedback.suggested_practice[:1],
                "needs_human_review": session.review.needs_human_review,
            }
        return {
            "session_id": session_id,
            "mode": viewer_role,
            "age_years": session.age_years,
            "age_band": session.assessment.age_band,
            "battery_id": session.battery_id,
            "task_results": [_task_payload(t) for t in session.battery_results],
            "expected_text": session.assessment.reference_text,
            "spoken_transcript": session.transcript.raw_transcript,
            "report": session.feedback.adult_feedback,
            "full_report": session.full_report.model_dump() if session.full_report else None,
            "scores": session.scores.model_dump(),
            "word_timeline": [w.model_dump() for w in session.alignment.word_alignment],
            "missed_words": session.alignment.missed_words,
            "changed_words": session.alignment.substituted_words,
            "target_sounds": [i.model_dump() for i in session.phonemes.target_phoneme_issues],
            "confidence": session.scores.confidence_score,
            "uncertainty": session.scores.metadata.uncertainty_notes,
            "evidence": [e.model_dump() for e in session.evidence],
            "needs_human_review": session.review.needs_human_review,
        }

    def get_full_report(self, session_id: str) -> Dict[str, Any]:
        session = self._session(session_id)
        if session.full_report is None:
            session.full_report = build_full_report(session)
        return session.full_report.model_dump()

    # POST /api/kids-voice/sessions/{session_id}/review
    def create_or_update_review(
        self,
        session_id: str,
        *,
        reason: List[str],
        reviewer_notes: str = "",
    ) -> HumanReviewCase:
        self._session(session_id)
        review_id = f"review_{session_id}"
        case = self.review_cases.get(review_id) or HumanReviewCase(
            review_id=review_id,
            session_id=session_id,
            reason=reason,
        )
        case.reason = reason
        case.reviewer_notes = reviewer_notes
        case.updated_at = now_iso()
        self.review_cases[review_id] = case
        return case

    # DELETE /api/kids-voice/recordings/{recording_id}
    def delete_recording(self, recording_id: str) -> AudioRecording:
        recording = self.recordings[recording_id]
        recording.deleted = True
        recording.raw_audio_uri = None
        recording.cleaned_audio_uri = None
        session = self.sessions.get(recording.session_id)
        if session:
            session.audio.raw_audio_uri = None
            session.audio.cleaned_audio_uri = None
            session.privacy.deletion_requested = True
            session.updated_at = now_iso()
        return recording

    # GET /api/kids-voice/children/{child_id}/progress
    def child_progress(self, child_id: str) -> Dict[str, Any]:
        child_sessions = [s for s in self.sessions.values() if s.child_id == child_id]
        scores = [s.scores.overall_score for s in child_sessions if s.status in {"completed", "needs_human_review"}]
        return {
            "child_id": child_id,
            "sessions": len(child_sessions),
            "average_overall_score": round(sum(scores) / len(scores), 3) if scores else None,
            "latest_level": child_sessions[-1].scores.developmental_level if child_sessions else None,
        }

    def _run_prompt(
        self,
        session: AssessmentSession,
        prompt_id: str,
        *,
        audio_overrides: Optional[Dict[str, Any]] = None,
        mock_transcript: Optional[str] = None,
    ) -> tuple[AssessmentPrompt, KidsVoiceAssessmentRunState, List[Any]]:
        prompt = self.prompts[prompt_id]
        assessment = session.assessment.model_copy(deep=True)
        assessment.prompt_id = prompt.prompt_id
        assessment.prompt_type = prompt.prompt_type
        assessment.reference_text = prompt.text
        assessment.reference_language = prompt.language_mode
        assessment.expected_script = prompt.script
        assessment.assessment_mode = prompt.assessment_mode

        state = KidsVoiceAssessmentRunState(
            assessment=assessment,
            audio=_audio_for_task(session, prompt_id, audio_overrides),
            transcript=session.transcript.model_copy(deep=True),
            nlp=session.nlp.model_copy(deep=True),
            alignment=session.alignment.model_copy(deep=True),
            phonemes=session.phonemes.model_copy(deep=True),
            scores=session.scores.model_copy(deep=True),
            feedback=session.feedback.model_copy(deep=True),
            review=ReviewState(),
            privacy=session.privacy.model_copy(deep=True),
            prompt=prompt,
            child_profile=ChildProfile(
                child_id=session.child_id,
                age_years=session.age_years,
                age_band=session.assessment.age_band,
                grade_band=session.assessment.grade_band,
                primary_language=session.assessment.primary_language,
                secondary_language=session.assessment.secondary_language,
            ),
            status=session.status,
            evidence=list(session.evidence),
        )
        start = len(state.evidence)
        pipeline = KidsVoiceAssessmentPipeline(provider=self.provider, config=self.config)
        result = pipeline.run(state, mock_transcript=mock_transcript)
        return prompt, result, result.evidence[start:]

    def _apply_single_result(
        self,
        session: AssessmentSession,
        prompt: AssessmentPrompt,
        result: KidsVoiceAssessmentRunState,
        new_evidence: List[Any],
    ) -> None:
        session.prompt_id = prompt.prompt_id
        session.assessment = result.assessment
        session.audio = result.audio
        session.transcript = result.transcript
        session.nlp = result.nlp
        session.alignment = result.alignment
        session.phonemes = result.phonemes
        session.scores = result.scores
        session.feedback = result.feedback
        session.review = result.review
        session.privacy = result.privacy
        session.evidence = result.evidence
        session.battery_results = [
            self._task_result_from_state(prompt, result, new_evidence)
        ]
        session.status = result.status
        session.full_report = build_full_report(session)
        session.updated_at = now_iso()

    def _task_result_from_state(
        self,
        prompt: AssessmentPrompt,
        result: KidsVoiceAssessmentRunState,
        evidence: List[Any],
    ) -> AssessmentTaskResult:
        return AssessmentTaskResult(
            prompt_id=prompt.prompt_id,
            prompt_text=prompt.text,
            display_text=prompt.display_text,
            assessment_mode=prompt.assessment_mode,
            assessment_domains=list(prompt.assessment_domains),
            status=result.status,
            audio=result.audio,
            transcript=result.transcript,
            nlp=result.nlp,
            alignment=result.alignment,
            phonemes=result.phonemes,
            scores=result.scores,
            feedback=result.feedback,
            review=result.review,
            evidence=list(evidence),
        )

    def _apply_battery_aggregate(self, session: AssessmentSession) -> None:
        results = session.battery_results
        if not results:
            return
        first = results[0]
        last = results[-1]
        session.prompt_id = first.prompt_id
        session.assessment.prompt_id = first.prompt_id
        session.assessment.reference_text = first.prompt_text
        session.assessment.prompt_type = self.prompts[first.prompt_id].prompt_type
        session.assessment.current_step = "battery_completed"
        session.audio = last.audio
        session.transcript = last.transcript
        session.nlp = last.nlp
        session.alignment = last.alignment
        session.phonemes = last.phonemes
        session.scores = _aggregate_scores(results)
        session.review = _aggregate_review(results)
        session.feedback = _aggregate_feedback(results, session.scores, session.review)
        statuses = {task.status for task in results}
        if "needs_retry" in statuses:
            session.status = "needs_retry"
        elif session.review.needs_human_review:
            session.status = "needs_human_review"
        else:
            session.status = "completed"
        session.full_report = build_full_report(session)
        session.updated_at = now_iso()

    def _session(self, session_id: str) -> AssessmentSession:
        if session_id not in self.sessions:
            raise KeyError(f"unknown session_id '{session_id}'")
        return self.sessions[session_id]

    def _load_config(self) -> Dict[str, Any]:
        path = self.example_dir / "agent_config.yaml"
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text()) or {}

    def _load_prompts(self) -> Dict[str, AssessmentPrompt]:
        prompts: Dict[str, AssessmentPrompt] = {}
        for path in sorted((self.example_dir / "prompts").glob("*.json")):
            if path.name == "allowed_hinglish_variants.json":
                continue
            data = json.loads(path.read_text())
            for item in data.get("prompts", data if isinstance(data, list) else []):
                prompt = AssessmentPrompt.model_validate(item)
                prompts[prompt.prompt_id] = prompt
        return prompts

    def _load_batteries(self) -> Dict[str, AssessmentBattery]:
        path = self.example_dir / "assessment_batteries.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text()) or {}
        return {
            item["battery_id"]: AssessmentBattery.model_validate(item)
            for item in data.get("batteries", [])
        }

    def _select_battery(
        self, age_years: Optional[int], battery_id: Optional[str]
    ) -> Optional[AssessmentBattery]:
        if battery_id:
            return self.batteries[battery_id]
        if age_years is None:
            return None
        for battery in self.batteries.values():
            if battery.age_min <= age_years <= battery.age_max:
                return battery
        return None

    def _build_configured_provider(self) -> VoiceProvider:
        provider_name = (
            self.config.get("runtime", {}).get("voice_provider")
            or self.config.get("elevenlabs", {}).get("provider")
        )
        if self.config.get("elevenlabs", {}).get("enabled") or provider_name == "elevenlabs":
            return ElevenLabsVoiceProvider(
                external_provider_allowed=bool(
                    self.config.get("privacy", {}).get("external_provider_allowed", False)
                )
            )
        if self.config.get("runtime", {}).get("allow_fixture_provider_for_local_demo", False):
            return MockVoiceProvider()
        raise RuntimeError("No real voice provider is configured.")


def age_band_for(age_years: Optional[int]) -> str:
    if age_years is None:
        return "5-6"
    if age_years <= 4:
        return "3-4"
    if age_years <= 6:
        return "5-6"
    return "7-8"


def _prompt_matches_age(prompt: AssessmentPrompt, age_years: int) -> bool:
    if prompt.age_min is not None or prompt.age_max is not None:
        return (prompt.age_min or 0) <= age_years <= (prompt.age_max or 99)
    return prompt.age_band == age_band_for(age_years)


def _should_run_battery(session: AssessmentSession) -> bool:
    return bool(session.battery_id and len(session.selected_prompt_ids) > 1)


def _task_input(
    task_inputs: Dict[str, Dict[str, Any]], prompt_id: str
) -> Dict[str, Any]:
    merged = dict(task_inputs.get("_default", {}))
    merged.update(task_inputs.get(prompt_id, {}))
    return merged


def _audio_for_task(
    session: AssessmentSession,
    prompt_id: str,
    overrides: Optional[Dict[str, Any]],
) -> AudioState:
    audio = session.audio.model_copy(deep=True)
    if not audio.recording_id:
        audio.recording_id = f"rec_{session.session_id}_{prompt_id}"
    audio_values = dict(overrides or {})
    nested = audio_values.get("audio")
    if isinstance(nested, dict):
        audio_values.update(nested)
    for key, value in audio_values.items():
        if key in AudioState.model_fields:
            setattr(audio, key, value)
    return audio


def _aggregate_scores(tasks: List[AssessmentTaskResult]) -> ScoreState:
    fields = [
        "word_accuracy",
        "reference_completeness",
        "phoneme_accuracy",
        "target_sound_score",
        "pronunciation_score",
        "fluency_score",
        "completeness_score",
        "pause_score",
        "speaking_confidence_score",
        "audio_quality_score",
        "confidence_score",
        "overall_score",
    ]
    values = {
        field: round(_avg([float(getattr(task.scores, field)) for task in tasks]), 3)
        for field in fields
    }
    confidence = values["confidence_score"]
    notes = sorted(
        {
            note
            for task in tasks
            for note in task.scores.metadata.uncertainty_notes
        }
    )
    return ScoreState(
        **values,
        developmental_level=map_score_to_developmental_level(values["overall_score"]),
        metadata=ModelMetadata(
            provider="local",
            model_version="battery-aggregate-v1",
            confidence=confidence,
            uncertainty_notes=notes,
        ),
    )


def _aggregate_review(tasks: List[AssessmentTaskResult]) -> ReviewState:
    reasons = sorted(
        {
            reason
            for task in tasks
            for reason in task.review.review_reason
        }
    )
    return ReviewState(
        needs_human_review=any(task.review.needs_human_review for task in tasks),
        review_reason=reasons,
        metadata=ModelMetadata(
            provider="local",
            model_version="battery-review-routing-v1",
            confidence=_avg([task.scores.confidence_score for task in tasks]),
        ),
    )


def _aggregate_feedback(
    tasks: List[AssessmentTaskResult],
    scores: ScoreState,
    review: ReviewState,
) -> FeedbackState:
    if any(task.status == "needs_retry" for task in tasks):
        child_feedback = "Mic ko thoda paas laao, phir se try karte hain."
    elif review.needs_human_review:
        child_feedback = "Nice effort! Parent ya teacher details check karenge, phir practice karenge."
    else:
        child_feedback = "Great! Tumne practice set complete kar liya."

    completed = len([task for task in tasks if task.status in {"completed", "needs_human_review"}])
    domains = sorted({domain for task in tasks for domain in task.assessment_domains})
    missed = [
        word
        for task in tasks
        for word in task.alignment.missed_words[:3]
    ]
    adult_parts = [
        f"The child completed {completed}/{len(tasks)} age-appropriate voice tasks.",
        f"Observed domains: {', '.join(domains) if domains else 'speech and language practice'}.",
        f"Overall educational practice level: {scores.developmental_level}.",
    ]
    if missed:
        adult_parts.append(f"Evidence showed skipped words such as {', '.join(missed[:5])}.")
    if review.needs_human_review:
        adult_parts.append(
            "Human review is recommended before making precise learning conclusions."
        )

    suggestions: List[str] = []
    for task in tasks:
        for item in task.feedback.suggested_practice:
            if item not in suggestions:
                suggestions.append(item)
    safety_notes = sorted(
        {
            note
            for task in tasks
            for note in task.feedback.safety_notes
        }
    )
    return FeedbackState(
        child_feedback=child_feedback,
        adult_feedback=" ".join(adult_parts),
        suggested_practice=suggestions[:5],
        safety_notes=safety_notes,
        should_suppress_child_feedback=review.needs_human_review,
        metadata=ModelMetadata(
            provider="local",
            model_version="battery-feedback-v1",
            confidence=scores.confidence_score,
        ),
    )


def _task_payload(task: AssessmentTaskResult) -> Dict[str, Any]:
    return {
        "prompt_id": task.prompt_id,
        "prompt_text": task.prompt_text,
        "status": task.status,
        "assessment_mode": task.assessment_mode,
        "domains": task.assessment_domains,
        "spoken_transcript": task.transcript.raw_transcript,
        "overall_score": task.scores.overall_score,
        "developmental_level": task.scores.developmental_level,
        "confidence": task.scores.confidence_score,
        "missed_words": task.alignment.missed_words,
        "changed_words": task.alignment.substituted_words,
        "needs_human_review": task.review.needs_human_review,
        "evidence": [item.id for item in task.evidence],
    }


def _avg(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)
