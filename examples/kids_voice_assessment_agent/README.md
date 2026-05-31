# BoloBuddy Voice Assessment

Kids Voice Assessment Agent is a SOPilot example for Hinglish-first,
child-safe voice assessment for modern Indian kids. It supports Indian English,
Hindi, Hinglish, Hindi written in Latin script, Hindi Devanagari, and
code-switching inside one utterance.

This is not a generic English pronunciation checker and it is not a clinical
diagnosis tool. The child sees playful practice feedback; adults get
explainable evidence, uncertainty, review status, and practice exercises.

## Why SOPilot

SOPilot keeps this product as a configurable SOP plus reusable runtime modules:

- The SOP describes child flow, retry rules, scoring, feedback, privacy, and
  human review.
- The central state keeps transcript, Hinglish NLP, alignment, phonemes, scores,
  feedback, review, privacy, and evidence separate.
- Tool/MCP contracts keep local fixtures separate from the production
  ElevenLabs-backed STT/alignment path.
- Human review gates are explicit and auditable.

## Age-Based Assessment

The child age is collected at session start. BoloBuddy chooses an age-matched
battery from `assessment_batteries.yaml`:

- Ages 3-4: short echo, naming, and one-step direction tasks.
- Ages 5-6: short sentence repetition, target sounds, and simple why questions.
- Ages 7-8: longer sentences, code-switch reading, story sequencing, and
  auditory memory tasks.

A 3-year-old is never given the same battery as an 8-year-old. Each prompt
declares the domains it can observe, such as speech clarity, expressive
language, receptive language, vocabulary, attention, phonological awareness,
working memory, code-switch control, processing fluency, and story/reasoning.

These are educational observations, not IQ scores or clinical diagnosis.

## Hinglish And Code-Switching

The NLP layer normalizes both reference and spoken text into token records:

```json
{"text": "phir", "normalized_text": "phir", "script": "latin", "language": "hi"}
```

Prompt metadata controls accepted variants. For example, `hinglish_l1_001`
allows `school -> iskool`, so "mera iskool bag ready hai" can be accepted without
making that equivalence global for every assessment.

Modes change strictness:

- `strict_reading`: substitutions count more.
- `sentence_reading`: prompt-scoped variants can be accepted.
- `expressive_speaking`: completeness, fluency, and confidence matter more than
  exact wording.
- `target_phoneme_only`: surrounding words are treated gently.

## ElevenLabs Usage

ElevenLabs is behind `VoiceProvider` adapters and is the production provider for
real assessment. Fixture mode exists only for local tests/demos where no child
audio or API key is available.

Potential production uses:

- TTS prompt playback with a friendly child-safe voice.
- Scribe v2 STT with language hints, keyterms, and word timestamps.
- Optional realtime STT only for gentle UI state.
- Audio Isolation for noisy homes/classrooms.
- Forced Alignment against the expected reference text.
- Optional short reward sounds, disabled in tests.
- Pronunciation dictionaries for Hinglish words, Hindi Latin spellings, and
  Indian-English words.

No API key is exposed to frontend code. External provider calls require both
server-side env vars and `privacy.external_provider_allowed: true`.

Production sessions fail closed if a real provider is required but only a
fixture provider is supplied.

## Expected MCP Tools

The local connector in `core.kids_voice_assessment.tools` exposes fixture
versions of these groups for SOPilot dry-runs:

- `mcp_hinglish_nlp`
- `mcp_phoneme_g2p`
- `mcp_pronunciation_assessment`
- `mcp_curriculum`
- `mcp_privacy_review`
- `mcp_elevenlabs_adapter`

The example config registers `kids_voice_local` so the generic SOPilot tool
router can discover the tools with no network.

## Run The Local Fixture Demo

Generic SOPilot dry run:

```bash
python -m sopilot run examples/kids_voice_assessment_agent --checkpointer memory
```

Domain pipeline demo:

```bash
python examples/kids_voice_assessment_agent/demo.py
```

The demo creates a child session, attaches symbolic fixture audio, runs the
full age-selected battery with `MockVoiceProvider`, and prints child and parent
payloads. This is not production scoring.

## Enable ElevenLabs

The checked-in config is already set to production provider mode:

```yaml
runtime:
  voice_provider: elevenlabs
  production_requires_real_stt_alignment: true
  allow_fixture_provider_for_local_demo: false
elevenlabs:
  enabled: true
privacy:
  external_provider_allowed: true
```

Then set server-side env vars:

```bash
export ELEVENLABS_API_KEY=...
export ELEVENLABS_STT_MODEL_ID=scribe_v2
export ELEVENLABS_TTS_MODEL_ID=...
export ELEVENLABS_VOICE_ID_CHILD_FRIENDLY=...
export ELEVENLABS_VOICE_ID_PARENT=...
export ELEVENLABS_USE_AUDIO_ISOLATION=true
export ELEVENLABS_USE_FORCED_ALIGNMENT=true
```

Production code should instantiate `ElevenLabsVoiceProvider` server-side only.

Real assessment path:

1. Parent/teacher consent.
2. Audio capture/upload.
3. Optional ElevenLabs Audio Isolation.
4. ElevenLabs Scribe v2 STT with keyterms, language detection/hints, and word
   timestamps.
5. ElevenLabs Forced Alignment against expected text.
6. BoloBuddy Hinglish NLP per task, age-battery aggregation, scoring, insights,
   exercises, privacy, and review gates.

## Privacy And Safety

- Parent or teacher consent is required before saving audio.
- `store_raw_audio=false` prevents raw audio URI persistence.
- Deletion clears raw and cleaned audio references and marks deletion state.
- PII redaction is enabled in config.
- Child mode never shows raw percentages or technical diagnostic labels.
- Low confidence suppresses detailed child feedback and creates review.
- Reports state that this is educational practice feedback, not diagnosis.
- Full reports state that this is not an IQ test.

## MVP Vs Production

MVP supports age-based word/sentence/expressive assessment, Hinglish
normalization, basic token language/script tags, ElevenLabs production adapter,
fixture-only local demo provider, forced-alignment adapter, fallback G2P,
gentle scoring, child/adult/full reports, a static UI demo, privacy controls,
and human review triggers.

MVP does not claim perfect phoneme recognition, clinical-grade assessment, IQ
measurement, robust ASR for all noisy child speech, or support for every Indian
language.

Production roadmap: fine-tuned child speech models, local CTC alignment, stronger
phoneme recognizer, classroom mode, specialist mode, progress dashboard,
adaptive curriculum, on-device low-latency mode, richer Hindi phoneme coverage,
and optional guided practice with ElevenLabs Agents.
