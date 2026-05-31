"""Voice adapter backed by ElevenLabs STT and TTS providers.

The adapter wraps the existing kids voice assessment provider layer so HTTP and
multipart behavior stays in one place. The provider is injectable, which keeps
unit tests deterministic with ``MockVoiceProvider``.
"""

from __future__ import annotations

from typing import Any, List, Optional

from core.adapters.base import (
    ActionRequest,
    ActionResult,
    Observation,
    ObserveRequest,
)
from core.kids_voice_assessment.models import AudioState


class ElevenLabsVoiceAdapter:
    """ElevenLabs-backed voice adapter satisfying the generic Adapter contract."""

    def __init__(self, *, name: str = "voice", provider: Optional[Any] = None) -> None:
        self.name = name
        if provider is None:
            from core.kids_voice_assessment.providers import ElevenLabsVoiceProvider

            provider = ElevenLabsVoiceProvider(external_provider_allowed=True)
        self._provider = provider

    def capabilities(self) -> List[str]:
        return ["observe", "act", "speak", "transcribe"]

    def observe(self, request: ObserveRequest) -> Observation:
        media = (request.inputs or {}).get("media", {}) or {}
        entry = media.get(request.step_id) or {}
        transcript = (entry.get("transcript") or "").strip()
        if transcript:
            content = {"transcript": transcript}
            if isinstance(entry.get("content"), dict):
                content.update(entry["content"])
            return Observation(
                step_id=request.step_id,
                source="voice",
                content=content,
                summary=transcript,
                confidence=_clamp_confidence(entry.get("confidence", 0.9)),
                evidence_refs=[entry.get("recording_id", "care_habits_transcript")],
                model=entry.get("model", "elevenlabs-agent"),
            )

        audio_path = entry.get("audio_path")
        if not audio_path:
            return Observation(
                step_id=request.step_id,
                source="voice",
                summary="No audio provided for this step.",
                confidence=0.0,
                model="elevenlabs",
            )

        recording_id = entry.get("recording_id", request.step_id)
        audio = AudioState(
            recording_id=recording_id,
            raw_audio_uri=audio_path,
            vad_speech_detected=True,
            quality_status="ok",
        )
        options = entry.get("options", {}) or {}
        try:
            result = self._provider.transcribe_audio(audio, options)
        except Exception as exc:
            return Observation(
                step_id=request.step_id,
                source="voice",
                summary=f"Voice transcription failed: {exc}",
                confidence=0.0,
                evidence_refs=[recording_id],
                model=getattr(self._provider, "provider", "elevenlabs"),
            )

        transcript = result.raw_transcript or ""
        confidence = _clamp_confidence(result.language_probability)
        model = getattr(self._provider, "provider", "elevenlabs")
        return Observation(
            step_id=request.step_id,
            source="voice",
            content={"transcript": transcript, "language_code": result.language_code},
            summary=transcript or "No speech detected.",
            confidence=confidence,
            evidence_refs=[recording_id],
            model=model,
        )

    def act(self, request: ActionRequest) -> ActionResult:
        text = (request.payload or {}).get("text", "")
        if not text:
            return ActionResult(ok=False, detail="No text to synthesize.")
        try:
            result = self._provider.synthesize_speech(text, request.payload or {})
        except Exception as exc:
            return ActionResult(ok=False, detail=f"Speech synthesis failed: {exc}")
        return ActionResult(
            ok=True,
            detail="Synthesized care-plan speech.",
            data={"audio_uri": result.audio_uri, "provider": result.provider},
        )


def _clamp_confidence(raw: Any) -> float:
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))
