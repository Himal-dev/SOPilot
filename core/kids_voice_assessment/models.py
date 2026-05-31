"""Typed models for the BoloBuddy Kids Voice Assessment example.

These models are deliberately provider-neutral. Every model output carries
provider/model/confidence/evidence metadata so downstream reports can distinguish
observed evidence from inference and uncertainty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


ScriptTag = Literal["latin", "devanagari", "mixed", "unknown"]
LanguageTag = Literal["en", "hi", "hinglish", "unknown"]
TokenSource = Literal["reference", "spoken"]
QualityStatus = Literal["ok", "retry", "failed", "needs_review"]
ViewerRole = Literal["child", "parent", "teacher", "specialist"]


class ModelMetadata(BaseModel):
    provider: str = "local"
    model_version: str = "mock-v1"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=now_iso)
    evidence_references: List[str] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    id: str
    kind: str
    summary: str
    uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HinglishToken(BaseModel):
    text: str
    normalized_text: str
    script: ScriptTag = "unknown"
    language: LanguageTag = "unknown"
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: TokenSource


class WordTimestamp(BaseModel):
    word: str
    start_ms: int
    end_ms: int
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class WordAlignmentItem(BaseModel):
    reference: Optional[str] = None
    spoken: Optional[str] = None
    status: Literal["matched", "missed", "inserted", "substituted", "variant"] = (
        "matched"
    )
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class PhonemeIssue(BaseModel):
    issue_type: Literal[
        "missed_word",
        "extra_word",
        "changed_word",
        "long_pause",
        "quick_rush",
        "target_sound_needs_practice",
        "unclear_audio",
        "low_confidence_model",
        "good_attempt",
    ]
    token: Optional[str] = None
    sound: Optional[str] = None
    child_label: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class AssessmentState(BaseModel):
    session_id: str = ""
    child_id: str = ""
    age_years: Optional[int] = None
    age_band: str = "6-8"
    grade_band: str = ""
    primary_language: str = "hinglish"
    secondary_language: Optional[str] = "en"
    assessment_mode: str = "sentence_reading"
    prompt_id: str = ""
    prompt_type: str = "sentence"
    reference_text: str = ""
    reference_language: str = "hinglish"
    expected_script: str = "latin"
    code_switch_policy: str = "allow_common_hinglish"
    current_step: str = "created"
    consent_status: str = "unknown"
    ui_mode: str = "child"


class AudioState(BaseModel):
    recording_id: str = ""
    raw_audio_uri: Optional[str] = None
    cleaned_audio_uri: Optional[str] = None
    duration_ms: int = 0
    sample_rate: int = 16000
    volume_score: float = Field(default=0.0, ge=0.0, le=1.0)
    noise_score: float = Field(default=1.0, ge=0.0, le=1.0)
    vad_speech_detected: bool = False
    quality_status: QualityStatus = "retry"
    retry_count: int = 0


class TranscriptState(BaseModel):
    raw_transcript: str = ""
    normalized_transcript: str = ""
    language_code: str = "unknown"
    language_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    words: List[str] = Field(default_factory=list)
    word_timestamps: List[WordTimestamp] = Field(default_factory=list)
    token_logprobs: List[float] = Field(default_factory=list)
    detected_code_switches: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class HinglishNlpState(BaseModel):
    normalized_reference: str = ""
    normalized_spoken: str = ""
    reference_tokens: List[HinglishToken] = Field(default_factory=list)
    spoken_tokens: List[HinglishToken] = Field(default_factory=list)
    token_language_tags: List[Dict[str, str]] = Field(default_factory=list)
    script_tags: List[Dict[str, str]] = Field(default_factory=list)
    allowed_reference_variants: Dict[str, List[str]] = Field(default_factory=dict)
    code_switch_events: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class AlignmentState(BaseModel):
    provider: str = "local"
    word_alignment: List[WordAlignmentItem] = Field(default_factory=list)
    character_alignment: List[Dict[str, Any]] = Field(default_factory=list)
    alignment_loss: float = 0.0
    matched_words: List[str] = Field(default_factory=list)
    missed_words: List[str] = Field(default_factory=list)
    inserted_words: List[str] = Field(default_factory=list)
    substituted_words: List[Dict[str, str]] = Field(default_factory=list)
    delayed_words: List[str] = Field(default_factory=list)
    uncertain_spans: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class PhonemeState(BaseModel):
    reference_phonemes: Dict[str, List[str]] = Field(default_factory=dict)
    spoken_phoneme_hypothesis: Dict[str, List[str]] = Field(default_factory=dict)
    phoneme_alignment: List[Dict[str, Any]] = Field(default_factory=list)
    target_phoneme_issues: List[PhonemeIssue] = Field(default_factory=list)
    accent_tolerance_profile: str = "indian_english_default"
    allowed_allophones: Dict[str, List[str]] = Field(default_factory=dict)
    phoneme_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class ScoreState(BaseModel):
    word_accuracy: float = 0.0
    reference_completeness: float = 0.0
    phoneme_accuracy: float = 0.0
    target_sound_score: float = 0.0
    pronunciation_score: float = 0.0
    fluency_score: float = 0.0
    completeness_score: float = 0.0
    pause_score: float = 0.0
    speaking_confidence_score: float = 0.0
    audio_quality_score: float = 0.0
    confidence_score: float = 0.0
    overall_score: float = 0.0
    developmental_level: str = "practicing"
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class FeedbackState(BaseModel):
    child_feedback: str = ""
    adult_feedback: str = ""
    suggested_practice: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)
    should_suppress_child_feedback: bool = False
    mode: ViewerRole = "child"
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class ReviewState(BaseModel):
    needs_human_review: bool = False
    review_reason: List[str] = Field(default_factory=list)
    reviewer_notes: str = ""
    corrected_transcript: Optional[str] = None
    corrected_scores: Optional[Dict[str, float]] = None
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class PrivacyState(BaseModel):
    consent_verified: bool = False
    raw_audio_retention: str = "30_days"
    deletion_requested: bool = False
    pii_redaction_applied: bool = False
    external_provider_usage: List[str] = Field(default_factory=list)
    store_raw_audio: bool = True
    external_provider_allowed: bool = False


class ChildProfile(BaseModel):
    child_id: str
    age_years: Optional[int] = None
    age_band: str
    grade_band: str = ""
    primary_language: str = "hinglish"
    secondary_language: Optional[str] = "en"
    created_at: str = Field(default_factory=now_iso)


class ConsentRecord(BaseModel):
    child_id: str
    granted_by: str = "parent_or_teacher"
    consent_status: Literal["verified", "missing", "revoked"] = "missing"
    consent_scope: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class AssessmentPrompt(BaseModel):
    prompt_id: str
    text: str
    display_text: str
    audio_prompt_text: str
    language_mode: str
    script: str
    age_band: str
    difficulty: str
    assessment_mode: str
    prompt_type: str = "sentence"
    target_words: List[str] = Field(default_factory=list)
    target_phonemes: List[str] = Field(default_factory=list)
    allowed_variants: Dict[str, List[str]] = Field(default_factory=dict)
    scoring_profile: str = "sentence_reading"
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    assessment_domains: List[str] = Field(default_factory=list)
    elicitation_type: str = "repeat_after_me"
    expected_response_type: str = "spoken"
    cognitive_load: str = "low"
    instructions_child: str = ""
    instructions_adult: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AssessmentBattery(BaseModel):
    battery_id: str
    title: str
    age_min: int
    age_max: int
    description: str = ""
    prompt_ids: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    estimated_minutes: int = 5
    report_focus: List[str] = Field(default_factory=list)


class AssessmentTaskResult(BaseModel):
    prompt_id: str
    prompt_text: str
    display_text: str = ""
    assessment_mode: str = "sentence_reading"
    assessment_domains: List[str] = Field(default_factory=list)
    status: str = "created"
    audio: AudioState = Field(default_factory=AudioState)
    transcript: TranscriptState = Field(default_factory=TranscriptState)
    nlp: HinglishNlpState = Field(default_factory=HinglishNlpState)
    alignment: AlignmentState = Field(default_factory=AlignmentState)
    phonemes: PhonemeState = Field(default_factory=PhonemeState)
    scores: ScoreState = Field(default_factory=ScoreState)
    feedback: FeedbackState = Field(default_factory=FeedbackState)
    review: ReviewState = Field(default_factory=ReviewState)
    evidence: List[EvidenceReference] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class AssessmentSession(BaseModel):
    session_id: str
    child_id: str
    prompt_id: str
    age_years: Optional[int] = None
    battery_id: Optional[str] = None
    selected_prompt_ids: List[str] = Field(default_factory=list)
    assessment_domains: List[str] = Field(default_factory=list)
    viewer_role: ViewerRole = "child"
    status: str = "created"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    assessment: AssessmentState = Field(default_factory=AssessmentState)
    audio: AudioState = Field(default_factory=AudioState)
    transcript: TranscriptState = Field(default_factory=TranscriptState)
    nlp: HinglishNlpState = Field(default_factory=HinglishNlpState)
    alignment: AlignmentState = Field(default_factory=AlignmentState)
    phonemes: PhonemeState = Field(default_factory=PhonemeState)
    scores: ScoreState = Field(default_factory=ScoreState)
    feedback: FeedbackState = Field(default_factory=FeedbackState)
    review: ReviewState = Field(default_factory=ReviewState)
    privacy: PrivacyState = Field(default_factory=PrivacyState)
    evidence: List[EvidenceReference] = Field(default_factory=list)
    battery_results: List[AssessmentTaskResult] = Field(default_factory=list)
    full_report: Optional[FullAssessmentReport] = None


class AudioRecording(BaseModel):
    recording_id: str
    session_id: str
    raw_audio_uri: Optional[str] = None
    cleaned_audio_uri: Optional[str] = None
    duration_ms: int = 0
    sample_rate: int = 16000
    deleted: bool = False
    created_at: str = Field(default_factory=now_iso)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class TranscriptResult(TranscriptState):
    pass


class HinglishTokenAnalysis(HinglishNlpState):
    pass


class AlignmentResult(AlignmentState):
    pass


class PhonemeAnalysisResult(PhonemeState):
    pass


class ScoreResult(ScoreState):
    pass


class PracticeRecommendation(BaseModel):
    skill: str
    activity: str
    mode: str = "practice"
    priority: str = "medium"
    evidence: List[str] = Field(default_factory=list)


class AssessmentInsight(BaseModel):
    domain: str
    label: str
    summary: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    severity: Literal["strength", "practice", "review"] = "practice"


class FullAssessmentReport(BaseModel):
    session_id: str
    child_id: str
    age_years: Optional[int] = None
    age_band: str
    battery_id: Optional[str] = None
    title: str = "BoloBuddy Voice Assessment Report"
    summary: str = ""
    assessment_battery: Dict[str, Any] = Field(default_factory=dict)
    domains: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    task_results: List[Dict[str, Any]] = Field(default_factory=list)
    insights: List[AssessmentInsight] = Field(default_factory=list)
    exercises: List[PracticeRecommendation] = Field(default_factory=list)
    evidence: List[EvidenceReference] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)
    human_review: ReviewState = Field(default_factory=ReviewState)
    disclaimer: str = (
        "This report provides educational observations from speech and language "
        "tasks. It is not an IQ test, clinical diagnosis, or measure of a child's worth."
    )
    created_at: str = Field(default_factory=now_iso)


class FeedbackReport(BaseModel):
    child_feedback: str
    parent_report: str
    teacher_report: Optional[str] = None
    specialist_report: Optional[str] = None
    suggested_practice: List[PracticeRecommendation] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class HumanReviewCase(BaseModel):
    review_id: str
    session_id: str
    reason: List[str]
    status: Literal["open", "in_review", "closed"] = "open"
    reviewer_notes: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


class AuditEvent(BaseModel):
    event_id: str
    session_id: str
    event_type: str
    actor: str = "system"
    detail: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class KidsVoiceAssessmentRunState(BaseModel):
    """Domain central state for the kids voice assessment graph/orchestrator."""

    assessment: AssessmentState = Field(default_factory=AssessmentState)
    audio: AudioState = Field(default_factory=AudioState)
    transcript: TranscriptState = Field(default_factory=TranscriptState)
    nlp: HinglishNlpState = Field(default_factory=HinglishNlpState)
    alignment: AlignmentState = Field(default_factory=AlignmentState)
    phonemes: PhonemeState = Field(default_factory=PhonemeState)
    scores: ScoreState = Field(default_factory=ScoreState)
    feedback: FeedbackState = Field(default_factory=FeedbackState)
    review: ReviewState = Field(default_factory=ReviewState)
    privacy: PrivacyState = Field(default_factory=PrivacyState)
    prompt: Optional[AssessmentPrompt] = None
    child_profile: Optional[ChildProfile] = None
    status: str = "created"
    evidence: List[EvidenceReference] = Field(default_factory=list)
    audit_events: List[AuditEvent] = Field(default_factory=list)
    final_child_result: Optional[Dict[str, Any]] = None
    final_adult_report: Optional[Dict[str, Any]] = None

    def add_evidence(
        self, kind: str, summary: str, uri: Optional[str] = None, **metadata: Any
    ) -> str:
        evidence_id = f"kids_ev_{len(self.evidence) + 1:04d}"
        self.evidence.append(
            EvidenceReference(
                id=evidence_id,
                kind=kind,
                summary=summary,
                uri=uri,
                metadata=metadata,
            )
        )
        return evidence_id
