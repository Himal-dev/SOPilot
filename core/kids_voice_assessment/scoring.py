"""Configurable gentle scoring for kids voice assessment."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.kids_voice_assessment.models import (
    AlignmentState,
    AudioState,
    ModelMetadata,
    PhonemeState,
    ScoreResult,
    TranscriptState,
)


DEFAULT_WEIGHTS: Dict[str, Dict[str, float]] = {
    "sentence_reading": {
        "word_accuracy": 0.30,
        "completeness": 0.25,
        "pronunciation": 0.20,
        "fluency": 0.15,
        "audio_quality": 0.05,
        "confidence": 0.05,
    },
    "strict_reading": {
        "word_accuracy": 0.40,
        "completeness": 0.25,
        "pronunciation": 0.20,
        "fluency": 0.10,
        "audio_quality": 0.025,
        "confidence": 0.025,
    },
    "word_pronunciation": {
        "target_sound": 0.45,
        "word_match": 0.25,
        "audio_quality": 0.10,
        "confidence": 0.20,
    },
    "expressive_speaking": {
        "fluency": 0.30,
        "completeness": 0.20,
        "clarity": 0.20,
        "confidence": 0.20,
        "audio_quality": 0.10,
    },
}


def calculate_scores(
    alignment: AlignmentState,
    audio: AudioState,
    transcript: TranscriptState,
    phonemes: PhonemeState,
    *,
    assessment_mode: str = "sentence_reading",
    weights: Dict[str, Dict[str, float]] | None = None,
) -> ScoreResult:
    weights = weights or DEFAULT_WEIGHTS
    profile = weights.get(assessment_mode, weights.get("sentence_reading", {}))

    total_ref = max(1, len([w for w in alignment.word_alignment if w.reference]))
    matched = len(
        [
            w
            for w in alignment.word_alignment
            if w.status in {"matched", "variant"} and w.reference
        ]
    )
    missed = len(alignment.missed_words)
    substituted = len(alignment.substituted_words)
    inserted = len(alignment.inserted_words)

    word_accuracy = _clamp((matched - 0.35 * inserted) / total_ref)
    if assessment_mode == "expressive_speaking":
        # Expressive mode cares less about exact articles/function words.
        word_accuracy = _clamp((matched + 0.5 * substituted) / total_ref)
    completeness = _clamp((total_ref - missed) / total_ref)
    phoneme_accuracy = _clamp(phonemes.phoneme_confidence)
    target_sound_score = _clamp(
        1.0 - 0.2 * len(phonemes.target_phoneme_issues)
    )
    audio_quality = _clamp((audio.volume_score + audio.noise_score) / 2)
    confidence = _average(
        [
            transcript.language_probability,
            alignment.metadata.confidence,
            phonemes.phoneme_confidence,
            audio_quality,
        ]
    )
    fluency = score_fluency(transcript.word_timestamps)
    pause = score_pause_patterns(transcript.word_timestamps)

    components = {
        "word_accuracy": word_accuracy,
        "word_match": word_accuracy,
        "completeness": completeness,
        "pronunciation": phoneme_accuracy,
        "target_sound": target_sound_score,
        "fluency": fluency,
        "clarity": word_accuracy,
        "audio_quality": audio_quality,
        "confidence": confidence,
    }
    overall = sum(components.get(k, 0.0) * v for k, v in profile.items())
    if not profile:
        overall = _average(components.values())

    return ScoreResult(
        word_accuracy=round(word_accuracy, 3),
        reference_completeness=round(completeness, 3),
        phoneme_accuracy=round(phoneme_accuracy, 3),
        target_sound_score=round(target_sound_score, 3),
        pronunciation_score=round(phoneme_accuracy, 3),
        fluency_score=round(fluency, 3),
        completeness_score=round(completeness, 3),
        pause_score=round(pause, 3),
        speaking_confidence_score=round(confidence, 3),
        audio_quality_score=round(audio_quality, 3),
        confidence_score=round(confidence, 3),
        overall_score=round(_clamp(overall), 3),
        developmental_level=map_score_to_developmental_level(overall),
        metadata=ModelMetadata(
            provider="local",
            model_version="gentle-scoring-v1",
            confidence=round(confidence, 3),
            uncertainty_notes=_score_uncertainty_notes(confidence, audio_quality),
        ),
    )


def score_word_pronunciation(status: str, phoneme_confidence: float) -> float:
    if status == "matched":
        return _clamp(0.85 + 0.15 * phoneme_confidence)
    if status == "variant":
        return _clamp(0.78 + 0.12 * phoneme_confidence)
    if status == "substituted":
        return 0.45
    return 0.25


def score_target_phoneme(found: bool, confidence: float) -> float:
    return _clamp(confidence if found else 0.35 * confidence)


def score_fluency(word_timestamps: Iterable[Any]) -> float:
    pauses = _pauses_ms(list(word_timestamps))
    if not pauses:
        return 0.78
    long_pauses = len([p for p in pauses if p > 1200])
    return _clamp(0.92 - 0.14 * long_pauses)


def score_pause_patterns(word_timestamps: Iterable[Any]) -> float:
    pauses = _pauses_ms(list(word_timestamps))
    if not pauses:
        return 0.78
    severe = len([p for p in pauses if p > 1800])
    moderate = len([p for p in pauses if 900 < p <= 1800])
    return _clamp(1.0 - 0.18 * severe - 0.08 * moderate)


def score_completeness(matched_or_variant: int, total_reference: int) -> float:
    return _clamp(matched_or_variant / max(1, total_reference))


def calibrate_for_age_band(score: float, age_band: str) -> float:
    if age_band == "3-5":
        return _clamp(score + 0.05)
    if age_band == "9-10":
        return _clamp(score - 0.02)
    return _clamp(score)


def generate_practice_recommendations(score: ScoreResult, issues: List[str]) -> List[str]:
    if score.audio_quality_score < 0.55:
        return ["Try once in a quieter spot with the mic closer."]
    if issues:
        return [f"Practice {issues[0]} slowly, then in the full sentence."]
    if score.reference_completeness < 0.85:
        return ["Read once with finger tracking so small words are not skipped."]
    return ["Do one cheerful repeat and then try the next prompt."]


def map_score_to_developmental_level(score: float) -> str:
    if score < 0.45:
        return "blooming"
    if score < 0.62:
        return "practicing"
    if score < 0.76:
        return "growing"
    if score < 0.88:
        return "confident"
    return "shining"


def _pauses_ms(word_timestamps: List[Any]) -> List[int]:
    pauses: List[int] = []
    for prev, cur in zip(word_timestamps, word_timestamps[1:]):
        prev_end = getattr(prev, "end_ms", None)
        cur_start = getattr(cur, "start_ms", None)
        if prev_end is not None and cur_start is not None:
            pauses.append(max(0, int(cur_start) - int(prev_end)))
    return pauses


def _score_uncertainty_notes(confidence: float, audio_quality: float) -> List[str]:
    notes: List[str] = []
    if confidence < 0.55:
        notes.append("Model confidence is low; prefer human review over precise correction.")
    if audio_quality < 0.55:
        notes.append("Recording quality may affect scoring.")
    return notes


def _average(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return _clamp(sum(values) / len(values))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
