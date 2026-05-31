"""Full educational report generation for BoloBuddy assessments."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from core.kids_voice_assessment.models import (
    AssessmentInsight,
    AssessmentSession,
    FullAssessmentReport,
    PracticeRecommendation,
)


DOMAIN_LABELS = {
    "speech_clarity": "Speech clarity",
    "expressive_language": "Expressive language",
    "receptive_language": "Listening and comprehension",
    "phonological_awareness": "Sound awareness",
    "working_memory": "Auditory working memory",
    "attention": "Listening attention",
    "narrative_reasoning": "Story and reasoning",
    "vocabulary": "Vocabulary",
    "code_switch_control": "Code-switch control",
    "processing_fluency": "Processing fluency",
}


def build_full_report(session: AssessmentSession) -> FullAssessmentReport:
    """Build the parent/teacher full report from a completed session.

    This reports educational observations from task performance. It deliberately
    avoids IQ claims or diagnosis labels.
    """

    domains = _domain_scores(session)
    task_results = _task_summaries(session)
    insights = _build_insights(session, domains)
    exercises = _build_exercises(session, insights)
    uncertainty = list(session.scores.metadata.uncertainty_notes)
    uncertainty.extend(session.feedback.safety_notes)
    for task in session.battery_results:
        uncertainty.extend(task.scores.metadata.uncertainty_notes)
        uncertainty.extend(task.feedback.safety_notes)
    if session.review.needs_human_review:
        uncertainty.append(
            "Human review is recommended before making precise developmental conclusions."
        )

    task_count = len(session.battery_results) or 1
    summary = (
        f"Assessment completed across {task_count} age-appropriate task(s) for "
        f"age {session.age_years or session.assessment.age_band}. "
        f"Overall educational practice level: {session.scores.developmental_level}. "
        "Use the domain notes as learning signals, not as an IQ score or diagnosis."
    )
    return FullAssessmentReport(
        session_id=session.session_id,
        child_id=session.child_id,
        age_years=session.age_years,
        age_band=session.assessment.age_band,
        battery_id=session.battery_id,
        summary=summary,
        assessment_battery=_battery_summary(session),
        domains=domains,
        task_results=task_results,
        insights=insights,
        exercises=exercises,
        evidence=list(session.evidence),
        uncertainty_notes=sorted(set(uncertainty)),
        human_review=session.review,
    )


def _battery_summary(session: AssessmentSession) -> Dict[str, object]:
    prompt_ids = session.selected_prompt_ids or [session.prompt_id]
    return {
        "battery_id": session.battery_id,
        "age_years": session.age_years,
        "age_band": session.assessment.age_band,
        "selected_prompt_ids": prompt_ids,
        "task_count": len(prompt_ids),
        "domains": session.assessment_domains,
        "age_appropriate_rationale": (
            "Prompt set selected from the child's age at session start; younger "
            "children receive shorter play-like tasks while older children receive "
            "longer code-switch, story, and memory tasks."
        ),
    }


def _domain_scores(session: AssessmentSession) -> Dict[str, Dict[str, object]]:
    if session.battery_results:
        return _battery_domain_scores(session)

    prompt_domains = session.assessment_domains
    domains = prompt_domains or ["speech_clarity", "expressive_language"]
    values: Dict[str, List[float]] = defaultdict(list)

    for domain in domains:
        values[domain].extend(_domain_values(domain, session.scores))

    return {
        domain: {
            "label": DOMAIN_LABELS.get(domain, domain.replace("_", " ").title()),
            "score": round(sum(scores) / max(1, len(scores)), 3),
            "level": _level(sum(scores) / max(1, len(scores))),
            "evidence": [e.id for e in session.evidence if e.kind in {"scores", "alignment", "transcript"}],
            "task_count": 1,
            "prompts": [session.prompt_id],
        }
        for domain, scores in values.items()
    }


def _battery_domain_scores(session: AssessmentSession) -> Dict[str, Dict[str, object]]:
    values: Dict[str, List[float]] = defaultdict(list)
    evidence: Dict[str, List[str]] = defaultdict(list)
    prompts: Dict[str, List[str]] = defaultdict(list)
    for task in session.battery_results:
        domains = task.assessment_domains or session.assessment_domains
        for domain in domains:
            values[domain].extend(_domain_values(domain, task.scores))
            evidence[domain].extend(
                item.id
                for item in task.evidence
                if item.kind in {"scores", "alignment", "transcript"}
            )
            prompts[domain].append(task.prompt_id)
    return {
        domain: {
            "label": DOMAIN_LABELS.get(domain, domain.replace("_", " ").title()),
            "score": round(sum(scores) / max(1, len(scores)), 3),
            "level": _level(sum(scores) / max(1, len(scores))),
            "evidence": sorted(set(evidence[domain])),
            "task_count": len(set(prompts[domain])),
            "prompts": prompts[domain],
        }
        for domain, scores in values.items()
    }


def _domain_values(domain: str, scores) -> List[float]:
    if domain == "speech_clarity":
        return [scores.pronunciation_score, scores.audio_quality_score]
    if domain == "expressive_language":
        return [scores.reference_completeness, scores.word_accuracy]
    if domain == "receptive_language":
        return [scores.completeness_score]
    if domain == "phonological_awareness":
        return [scores.target_sound_score, scores.phoneme_accuracy]
    if domain == "working_memory":
        return [scores.reference_completeness, scores.pause_score]
    if domain == "attention":
        return [scores.speaking_confidence_score, scores.pause_score]
    if domain == "narrative_reasoning":
        return [scores.fluency_score, scores.completeness_score]
    if domain == "vocabulary":
        return [scores.word_accuracy]
    if domain == "code_switch_control":
        return [scores.word_accuracy, scores.fluency_score]
    if domain == "processing_fluency":
        return [scores.fluency_score, scores.pause_score]
    return [scores.overall_score]


def _build_insights(
    session: AssessmentSession, domains: Dict[str, Dict[str, object]]
) -> List[AssessmentInsight]:
    insights: List[AssessmentInsight] = []
    for domain, payload in domains.items():
        score = float(payload["score"])
        severity = "strength" if score >= 0.78 else "review" if score < 0.45 else "practice"
        label = payload["label"]
        if severity == "strength":
            summary = f"{label} looked comfortable in this task."
        elif severity == "review":
            summary = f"{label} needs cautious interpretation because confidence or task completion was low."
        else:
            summary = f"{label} is a good practice area for the next sessions."
        insights.append(
            AssessmentInsight(
                domain=domain,
                label=str(label),
                summary=summary,
                evidence=list(payload.get("evidence", [])),
                confidence=session.scores.confidence_score,
                severity=severity,
            )
        )
    if session.alignment.missed_words:
        missed = session.alignment.missed_words
        evidence = [e.id for e in session.evidence if e.kind == "alignment"]
        confidence = session.alignment.metadata.confidence
    else:
        missed = [
            word
            for task in session.battery_results
            for word in task.alignment.missed_words
        ]
        evidence = [
            item.id
            for task in session.battery_results
            for item in task.evidence
            if item.kind == "alignment"
        ]
        confidence = session.scores.confidence_score
    if missed:
        insights.append(
            AssessmentInsight(
                domain="expressive_language",
                label="Small word completion",
                summary=(
                    "Small function words were skipped in the reading task; this can be "
                    "practiced with slow finger-tracking."
                ),
                evidence=evidence,
                confidence=confidence,
                severity="practice",
            )
        )
    return insights


def _task_summaries(session: AssessmentSession) -> List[Dict[str, object]]:
    return [
        {
            "prompt_id": task.prompt_id,
            "prompt_text": task.prompt_text,
            "assessment_mode": task.assessment_mode,
            "domains": task.assessment_domains,
            "status": task.status,
            "spoken_transcript": task.transcript.raw_transcript,
            "overall_score": task.scores.overall_score,
            "developmental_level": task.scores.developmental_level,
            "confidence": task.scores.confidence_score,
            "missed_words": task.alignment.missed_words,
            "changed_words": task.alignment.substituted_words,
            "uncertainty": task.scores.metadata.uncertainty_notes,
            "evidence": [item.id for item in task.evidence],
        }
        for task in session.battery_results
    ]


def _build_exercises(
    session: AssessmentSession, insights: Iterable[AssessmentInsight]
) -> List[PracticeRecommendation]:
    exercises: List[PracticeRecommendation] = []
    seen = set()
    for insight in insights:
        if insight.severity == "strength":
            continue
        activity = _exercise_for(insight.domain, session.assessment.age_band)
        key = (insight.domain, activity)
        if key in seen:
            continue
        seen.add(key)
        exercises.append(
            PracticeRecommendation(
                skill=insight.label,
                activity=activity,
                mode="home_practice",
                priority="high" if insight.severity == "review" else "medium",
                evidence=insight.evidence,
            )
        )
    if not exercises:
        exercises.append(
            PracticeRecommendation(
                skill="Confidence",
                activity="Do one cheerful repeat, then try a slightly longer prompt.",
                mode="home_practice",
                priority="low",
            )
        )
    return exercises[:5]


def _exercise_for(domain: str, age_band: str) -> str:
    if age_band == "3-4":
        mapping = {
            "speech_clarity": "Play a two-word echo game: red ball, blue bag, happy robot.",
            "expressive_language": "Ask the child to name one object and one color during play.",
            "receptive_language": "Give one playful instruction: touch the bag, then say bag.",
            "working_memory": "Repeat two familiar words with a clap between them.",
        }
    elif age_band == "5-6":
        mapping = {
            "phonological_awareness": "Pick one target sound and say three fun words slowly.",
            "expressive_language": "Use one full sentence about school, lunchbox, or a robot.",
            "working_memory": "Repeat a short sentence after hearing it once.",
            "narrative_reasoning": "Tell what happened first and next in a tiny story.",
        }
    else:
        mapping = {
            "code_switch_control": "Read one Hinglish sentence slowly, then explain it in your own words.",
            "narrative_reasoning": "Tell a three-step story: start, what changed, what happened next.",
            "working_memory": "Listen to a longer sentence and repeat it with all small words.",
            "processing_fluency": "Practice one sentence twice: first slowly, then storyteller speed.",
        }
    return mapping.get(domain, "Practice one short sentence slowly, then say it again with confidence.")


def _level(score: float) -> str:
    if score < 0.45:
        return "needs_review"
    if score < 0.62:
        return "emerging"
    if score < 0.78:
        return "developing"
    return "comfortable"
