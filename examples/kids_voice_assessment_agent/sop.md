# BoloBuddy Voice Assessment

Operational SOP for a Hinglish-first, child-safe voice assessment. The child
experience must feel like playful practice. Adult reports must be diagnostic,
explainable, evidence-backed, and explicitly non-clinical.

## Assessment Objective

- Assess Indian English, Hindi, Hinglish, Hindi Latin script, Hindi Devanagari, and code-switched child speech in short word/sentence tasks.
- Ask for the child's age in years at session start and choose an age-appropriate assessment battery for ages 3-4, 5-6, or 7-8.
- Use different questions by age so a 3-year-old receives short play-like prompts and an 8-year-old receives longer code-switch, story, and memory prompts.
- Recognize child speech patterns including pauses, skips, substitutions, repetitions, short utterances, background noise, and developing pronunciation.
- Produce educational observations across speech clarity, expressive/receptive language, vocabulary, listening attention, phonological awareness, auditory working memory, code-switch control, processing fluency, and story/reasoning tasks.
- Separate child-facing encouragement from parent, teacher, and specialist evidence views.
- Do not claim IQ, clinical diagnosis, intelligence ranking, or label a child.

## Child Mode Flow

- Load assessment config [tool: get_prompt_by_skill] [produces: assessment_config]
- Select age-based assessment battery [tool: select_next_prompt] [produces: assessment_battery]
- Present prompt [reason] [produces: prompt_presentation]
- Maybe generate prompt audio [tool: synthesize_prompt_audio] [produces: prompt_audio]
- Capture audio [voice] [evidence: raw_recording] [produces: recording]
- Validate audio quality [tool: log_audit_event] [produces: audio_quality]
- Maybe clean audio [tool: isolate_voice] [produces: cleaned_audio]
- Transcribe audio [tool: transcribe_audio] [produces: transcript]
- Normalize Hinglish [tool: normalize_hinglish_text, detect_script_per_token, detect_language_per_token, normalize_child_asr_artifacts] [produces: hinglish_nlp]
- Generate reference variants [tool: generate_code_switch_variants] [produces: reference_variants]
- Align to reference [tool: forced_align, compare_reference_to_spoken_tokens] [produces: alignment]
- Run phoneme analysis [tool: g2p_indian_english_variants, g2p_hindi_devanagari, g2p_hindi_latin, get_allowed_allophones] [produces: phoneme_analysis]
- Calculate scores [tool: score_word_pronunciation, score_fluency, score_pause_patterns, score_completeness, map_score_to_developmental_level] [produces: scores]
- Generate feedback [tool: generate_practice_recommendations] [produces: feedback]
- Persist assessment [tool: log_audit_event] [produces: persistence]
- Maybe trigger human review [tool: create_human_review_case] [review: compliance_fail] [produces: human_review]
- Return child result [reason] [produces: child_result]
- Return adult report [reason] [produces: adult_report]
- Return full assessment report with insights and exercises [reason] [produces: full_report]

## Parent And Teacher Mode Flow

- Verify parental consent before saving or processing child audio.
- Show expected text, spoken transcript, word timeline, missed or changed words, target sounds to practice, numeric scores, confidence, uncertainty notes, suggested activities, and review state.
- Show the selected age battery and explain why the tasks were age appropriate.
- Show domain-level educational insights and suggested exercises for home/classroom practice.
- Distinguish audio quality issues from pronunciation or reading evidence.
- Explain uncertainty and include evidence references for every major model output.
- Keep specialist phoneme details optional and behind role-based access.

## Retry Rules

- Retry gently when speech is not detected, volume is low, noise is high, the sample is too short, or clipping is detected.
- Use child-safe microcopy such as "Mic ko thoda paas laao, phir se try karte hain."
- If quality remains low after the configured retry count, create human review or soft completion instead of precise correction.
- Realtime STT, if enabled, can drive gentle states like "Main sun raha hoon" or "keep going"; it must not correct the child while speaking.

## Scoring Rubric

- Word accuracy: exact or configured variant match against the reference.
- Reference completeness: expected words attempted or acceptably substituted by configured mode.
- Phoneme and target sound score: fallback G2P plus optional recognizer confidence, with Indian English and Hindi tolerance profiles.
- Fluency and pause score: long pauses and rushed sections are noted gently.
- Audio quality score: volume, noise, VAD, and clipping.
- Overall score: configurable by age band, assessment mode, language mode, prompt difficulty, and target phoneme.
- Domain insights: educational observations for cognitive-language tasks such as attention, working memory, story sequencing, vocabulary, and reasoning. Do not present these as IQ or diagnosis.
- Developmental labels: blooming, practicing, growing, confident, shining.

## Code-Switch Policy

- strict_reference: count substitutions during strict reading.
- allow_common_hinglish: accept prompt-scoped common variants such as school/iskool or under/ke under.
- allow_semantic_equivalent: allow configured Hindi/English equivalents in expressive mode.
- free_speech: prioritize fluency, completeness, confidence, and evidence over exact word match.
- target_phoneme_only: score target words or sounds while being gentle about surrounding words.

## Feedback Policy

- Child feedback is one warm sentence, no raw percentages, no clinical terms, no IPA unless mapped to child-friendly labels.
- Parent and teacher feedback includes evidence, uncertainty, and suggested practice.
- Specialist feedback may include IPA and phoneme alignment with confidence.
- Suppress detailed child-facing correction when model confidence is low or sensitive concern is detected.
- Avoid shame-based words and labels: wrong, bad, poor, failed, problem child, disorder, abnormal.

## Human Review Triggers

- Low model confidence.
- Low alignment confidence.
- Low phoneme confidence.
- Repeated low score across sessions.
- Parent or teacher requested review.
- Sensitive developmental signal.
- Audio remains unclear after configured retries.

## Privacy Policy

- Parent or teacher consent is required before saving raw audio.
- Honor store_raw_audio=false by keeping only derived references.
- Keep raw and cleaned audio references separate.
- Deletion requests must clear recording URIs and mark deletion state.
- Redact PII in transcripts when enabled.
- External providers, including ElevenLabs, run only when privacy.external_provider_allowed=true and server-side keys are configured.
- Log audit events for external provider calls and human review access.

## Output Requirements

- Return child_feedback for child mode.
- Return adult_feedback, scores, evidence, uncertainty, timeline, and review state for parent or teacher mode.
- Persist transcript, Hinglish NLP, alignment, phoneme analysis, scores, feedback, privacy, and review decisions as evidence-backed structured outputs.
- State clearly that the result is educational practice feedback, not diagnosis.
