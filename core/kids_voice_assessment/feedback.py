"""Deterministic child-safe and adult-explainable feedback."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List

from core.kids_voice_assessment.models import (
    AlignmentState,
    FeedbackState,
    ModelMetadata,
    PhonemeState,
    ScoreState,
)
from core.kids_voice_assessment.scoring import generate_practice_recommendations


DEFAULT_BANNED_WORDS = [
    "wrong",
    "bad",
    "poor",
    "failed",
    "problem child",
    "disorder",
    "abnormal",
]

DEFAULT_CHILD_TEMPLATES = {
    "good_attempt": "Nice try! Tumne achha effort kiya.",
    "retry_audio": "Mic ko thoda paas laao, phir se try karte hain.",
    "missed_word": "Great effort! Ek chhota word miss hua - chalo fir se bolte hain.",
    "target_sound": "Super! Ab '{sound}' sound ko slowly practice karte hain.",
    "clear_sentence": "Super effort! Tumne sentence kaafi clearly bola.",
    "low_confidence": "Nice try! Ek baar aur softly and clearly try karte hain.",
}


def generate_feedback(
    scores: ScoreState,
    alignment: AlignmentState,
    phonemes: PhonemeState,
    *,
    audio_quality_ok: bool = True,
    tone: str = "hinglish_warm",
    banned_words: Iterable[str] = DEFAULT_BANNED_WORDS,
    child_templates: Dict[str, str] | None = None,
) -> FeedbackState:
    templates = {**DEFAULT_CHILD_TEMPLATES, **(child_templates or {})}
    suppress_child = scores.confidence_score < 0.45
    safety_notes: List[str] = []

    if not audio_quality_ok:
        child = templates["retry_audio"]
        safety_notes.append("Audio quality issue; scoring should not be shown to child.")
    elif suppress_child:
        child = templates["low_confidence"]
        safety_notes.append("Low model confidence; child diagnostic details suppressed.")
    elif alignment.missed_words:
        child = templates["missed_word"]
    elif phonemes.target_phoneme_issues:
        sound = phonemes.target_phoneme_issues[0].child_label or (
            phonemes.target_phoneme_issues[0].sound or "target"
        )
        child = templates["target_sound"].format(sound=sound)
    elif scores.overall_score >= 0.78:
        child = templates["clear_sentence"]
    else:
        child = templates["good_attempt"]

    if tone == "english_warm":
        child = _to_english_child_feedback(child)
    elif tone == "hindi_warm":
        child = _to_hindi_latin_child_feedback(child)

    child = _safe_text(child, banned_words)
    adult = _build_adult_feedback(scores, alignment, phonemes)
    adult = _safe_text(adult, banned_words)
    practice = generate_practice_recommendations(
        scores,
        [
            issue.child_label or issue.sound or issue.issue_type
            for issue in phonemes.target_phoneme_issues
        ],
    )
    return FeedbackState(
        child_feedback=child,
        adult_feedback=adult,
        suggested_practice=practice,
        safety_notes=safety_notes,
        should_suppress_child_feedback=suppress_child,
        metadata=ModelMetadata(
            provider="local",
            model_version="feedback-templates-v1",
            confidence=scores.confidence_score,
            uncertainty_notes=scores.metadata.uncertainty_notes,
        ),
    )


def child_result_payload(feedback: FeedbackState, scores: ScoreState) -> Dict[str, object]:
    """Child mode payload intentionally excludes raw percentages."""
    return {
        "mode": "child",
        "feedback": feedback.child_feedback,
        "developmental_level": scores.developmental_level,
        "suggested_practice": feedback.suggested_practice[:1],
        "show_raw_scores": False,
        "safety_notes": feedback.safety_notes,
    }


def adult_report_payload(
    feedback: FeedbackState,
    scores: ScoreState,
    alignment: AlignmentState,
    *,
    evidence: List[Dict[str, object]],
) -> Dict[str, object]:
    return {
        "mode": "adult",
        "feedback": feedback.adult_feedback,
        "scores": scores.model_dump(),
        "word_timeline": [w.model_dump() for w in alignment.word_alignment],
        "missed_words": alignment.missed_words,
        "inserted_words": alignment.inserted_words,
        "substituted_words": alignment.substituted_words,
        "uncertainty": scores.metadata.uncertainty_notes,
        "suggested_practice": feedback.suggested_practice,
        "evidence": evidence,
    }


def contains_banned_words(text: str, banned_words: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(word.lower())}\b", lowered) for word in banned_words)


def _safe_text(text: str, banned_words: Iterable[str]) -> str:
    replacements = {
        "wrong": "changed",
        "bad": "needs another try",
        "poor": "needs support",
        "failed": "needs a retry",
        "problem child": "child",
        "disorder": "developmental concern",
        "abnormal": "unexpected",
    }
    safe = text
    for banned in banned_words:
        safe = re.sub(
            rf"\b{re.escape(banned)}\b",
            replacements.get(banned.lower(), "needs review"),
            safe,
            flags=re.IGNORECASE,
        )
    return safe


def _build_adult_feedback(
    scores: ScoreState, alignment: AlignmentState, phonemes: PhonemeState
) -> str:
    total = len([w for w in alignment.word_alignment if w.reference])
    completed = len(
        [
            w
            for w in alignment.word_alignment
            if w.reference and w.status in {"matched", "variant"}
        ]
    )
    parts = [
        f"The child completed {completed}/{max(1, total)} expected words.",
    ]
    if alignment.missed_words:
        missed = ", ".join(alignment.missed_words)
        parts.append(f"Skipped word(s): {missed}.")
    if alignment.substituted_words:
        changed = ", ".join(
            f"{item.get('reference')} -> {item.get('spoken')}"
            for item in alignment.substituted_words
        )
        parts.append(f"Changed word evidence: {changed}.")
    if phonemes.target_phoneme_issues:
        labels = ", ".join(
            issue.child_label or issue.sound or issue.issue_type
            for issue in phonemes.target_phoneme_issues
        )
        parts.append(f"Target sound practice suggested: {labels}.")
    parts.append(
        f"Fluency was {scores.developmental_level} with confidence {scores.confidence_score:.2f}."
    )
    if scores.metadata.uncertainty_notes:
        parts.append("Uncertainty: " + " ".join(scores.metadata.uncertainty_notes))
    parts.append("This is an educational assessment, not a clinical diagnosis.")
    return " ".join(parts)


def _to_english_child_feedback(text: str) -> str:
    if "Mic ko" in text:
        return "Bring the mic a little closer, then let's try again."
    if "Ek chhota word" in text:
        return "Great effort! One tiny word was missed - let's say it again."
    if "slowly practice" in text:
        return text.replace("Ab", "Now").replace("karte hain", "together.")
    return "Nice try! You put in lovely effort."


def _to_hindi_latin_child_feedback(text: str) -> str:
    if "Mic ko" in text:
        return text
    if "Nice try" in text:
        return "Bahut accha effort! Chalo ek baar aur practice karte hain."
    return text
