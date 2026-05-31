---
name: create_kids_voice_assessment_agent
description: >
  Create a child-safe Hinglish-first voice assessment SOPilot agent from an SOP.
  Use when building agents that assess Indian English, Hindi, Hinglish,
  code-switched child speech, phoneme targets, privacy gates, and separate
  child/adult feedback without clinical diagnosis claims.
---

# Create A Kids Voice Assessment Agent

Use this skill to turn a child voice practice SOP into a production-minded
SOPilot agent with mockable providers, prompt-scoped Hinglish variants, gentle
scoring, privacy controls, and human review.

## Required Inputs

- Product name and target age/grade bands.
- Exact child age collection requirement at session start.
- Assessment modes: word, sentence, phonics, story line, or expressive speaking.
- Language modes: Indian English, Hindi, Hinglish, code-switch.
- Prompt set with target words, target phonemes, difficulty, and accepted variants.
- Privacy policy: consent, retention, deletion, external provider allowance.
- Human review triggers and adult report requirements.

## Steps

1. Create `examples/<agent_name>/` with `README.md`, `sop.md`,
   `agent_config.yaml`, `output_schema.json`, `prompts/`, `sample_inputs/`,
   `sample_outputs/`, `assessment_batteries.yaml`, and optional `ui/`.
2. Write the SOP as a real operating procedure: objective, child mode,
   parent/teacher mode, retry rules, scoring rubric, feedback policy, human
   review triggers, privacy policy, and output requirements.
3. Define age batteries first. For ages 3-8, split at least into 3-4, 5-6, and
   7-8 so a 3-year-old never receives the same battery as an 8-year-old.
4. Configure prompt sets. Each prompt needs `prompt_id`, `text`, `display_text`,
   `audio_prompt_text`, `language_mode`, `script`, `age_band`, `difficulty`,
   `assessment_mode`, `target_words`, `target_phonemes`, `allowed_variants`, and
   `scoring_profile`. Add `age_min`, `age_max`, `assessment_domains`,
   `elicitation_type`, and `cognitive_load` for full reports.
5. Keep language/code-switching prompt-scoped. Put variants like `school/iskool`,
   `under/neeche`, or `story/kahani` in prompt metadata or a referenced variants
   file. Do not make broad global equivalence rules unless the curriculum owns
   them.
6. Define scoring weights by age band, assessment mode, language mode, prompt
   difficulty, and target phoneme. Use gentle labels: blooming, practicing,
   growing, confident, shining.
7. Add phoneme targets with an accent tolerance profile. Avoid rigid US/UK
   accent scoring for Indian English. Treat v/w, th/t, leading vowel before
   school, and Hindi aspirated/retroflex distinctions according to the selected
   profile.
8. Add provider seams. Production assessment should use real ElevenLabs STT and
   Forced Alignment. Keep fixture/mock providers only for local tests/demos, and
   fail closed when production requires real STT/alignment but a fixture provider
   is supplied.
9. Add MCP/local tool contracts for Hinglish NLP, phoneme G2P, pronunciation
   assessment, curriculum, privacy/review, and ElevenLabs adapter operations.
10. Separate feedback modes. Child feedback is one warm sentence with no raw
   scores or diagnosis. Adult feedback includes evidence, uncertainty, and
   practice suggestions. Specialist mode may include IPA only when configured.
11. Set privacy and human review gates: consent required, deletion supported,
    PII redaction, external provider allowance, audit events, and review on low
    confidence or sensitive signals.
12. Add deterministic samples: transcripts, word timestamps, alignment, phoneme
    outputs, low-quality audio, and expected child/adult reports.
13. Add focused tests for config loading, fixture provider determinism, audio retry,
    Hinglish normalization, token language/script tags, variant policy,
    scoring-mode differences, banned feedback words, child/adult payload
    separation, deletion, human review, and sample schema validation.

## Validation Checklist

- The mock demo runs with no external keys.
- Age is collected at session start and selects an age-matched battery.
- Full report includes educational domain insights and exercises.
- ElevenLabs keys are never exposed to frontend code.
- `privacy.external_provider_allowed=false` blocks real provider calls.
- Production mode does not use mock STT/alignment.
- Child mode hides raw percentages and technical diagnostic labels.
- Adult mode includes evidence and uncertainty.
- Low confidence routes to human review instead of precise correction.
- `strict_reading` is stricter than `expressive_speaking`.
- Accepted Hinglish variants are controlled by prompt/config.
- Feedback avoids banned words such as wrong, bad, poor, failed, disorder, and
  abnormal.
- Documentation states MVP limits and does not claim clinical-grade assessment.
- Documentation does not claim IQ, intelligence ranking, or diagnosis.
