"""LangGraph wiring for the Kids Voice Assessment pipeline."""

from __future__ import annotations

from typing import Callable

from langgraph.graph import END, START, StateGraph

from core.kids_voice_assessment.models import KidsVoiceAssessmentRunState
from core.kids_voice_assessment.pipeline import KidsVoiceAssessmentPipeline


KIDS_VOICE_NODES = [
    "load_assessment_config",
    "present_prompt",
    "maybe_generate_prompt_audio",
    "capture_audio",
    "validate_audio_quality",
    "maybe_clean_audio",
    "transcribe_audio",
    "normalize_hinglish",
    "generate_reference_variants",
    "align_to_reference",
    "run_phoneme_analysis",
    "calculate_scores",
    "generate_feedback",
    "persist_assessment",
    "maybe_trigger_human_review",
    "return_child_result",
    "return_adult_report",
]


def build_kids_voice_graph(pipeline: KidsVoiceAssessmentPipeline):
    """Build a domain graph with explicit product node names."""
    graph = StateGraph(KidsVoiceAssessmentRunState)
    for name in KIDS_VOICE_NODES:
        graph.add_node(name, _node(pipeline, name))

    graph.add_edge(START, "load_assessment_config")
    graph.add_conditional_edges(
        "load_assessment_config",
        _route_consent,
        {"stop": END, "present_prompt": "present_prompt"},
    )
    graph.add_edge("present_prompt", "maybe_generate_prompt_audio")
    graph.add_edge("maybe_generate_prompt_audio", "capture_audio")
    graph.add_edge("capture_audio", "validate_audio_quality")
    graph.add_conditional_edges(
        "validate_audio_quality",
        _route_quality,
        {"retry_or_review": "generate_feedback", "continue": "maybe_clean_audio"},
    )
    graph.add_edge("maybe_clean_audio", "transcribe_audio")
    graph.add_edge("transcribe_audio", "normalize_hinglish")
    graph.add_edge("normalize_hinglish", "generate_reference_variants")
    graph.add_edge("generate_reference_variants", "align_to_reference")
    graph.add_edge("align_to_reference", "run_phoneme_analysis")
    graph.add_edge("run_phoneme_analysis", "calculate_scores")
    graph.add_edge("calculate_scores", "generate_feedback")
    graph.add_conditional_edges(
        "generate_feedback",
        _route_after_feedback,
        {"finish_child": "return_child_result", "persist": "persist_assessment"},
    )
    graph.add_edge("persist_assessment", "maybe_trigger_human_review")
    graph.add_conditional_edges(
        "maybe_trigger_human_review",
        _route_viewer,
        {"child": "return_child_result", "adult": "return_adult_report"},
    )
    graph.add_edge("return_child_result", END)
    graph.add_edge("return_adult_report", END)
    return graph


def compile_kids_voice_graph(pipeline: KidsVoiceAssessmentPipeline):
    return build_kids_voice_graph(pipeline).compile()


def _node(
    pipeline: KidsVoiceAssessmentPipeline, name: str
) -> Callable[[KidsVoiceAssessmentRunState], dict]:
    def run(state: KidsVoiceAssessmentRunState) -> dict:
        updated = getattr(pipeline, name)(state)
        return updated.model_dump()

    return run


def _route_consent(state: KidsVoiceAssessmentRunState) -> str:
    return "present_prompt" if state.privacy.consent_verified else "stop"


def _route_quality(state: KidsVoiceAssessmentRunState) -> str:
    return "continue" if state.audio.quality_status == "ok" else "retry_or_review"


def _route_after_feedback(state: KidsVoiceAssessmentRunState) -> str:
    return "finish_child" if state.audio.quality_status != "ok" else "persist"


def _route_viewer(state: KidsVoiceAssessmentRunState) -> str:
    return "child" if state.assessment.ui_mode == "child" else "adult"
