# ElevenLabs Capabilities For BoloBuddy

Verified against official ElevenLabs documentation on 2026-05-30.

## What ElevenLabs Provides

ElevenLabs exposes a broad audio API surface, including Text to Speech, Speech
to Text, Music, Text to Dialogue, Voice Changer, Voice Isolator, Dubbing, Sound
Effects, Voice Design, Voice Remixing, Forced Alignment, Pronunciation
Dictionaries, Audio Native, and Agents Platform/Voice Agents.

Sources:

- https://elevenlabs.io/api
- https://elevenlabs.io/docs/overview/intro

## Capabilities Relevant To Kids Voice Assessment

### Speech To Text

Use Scribe v2 for real transcription. Official docs describe:

- accurate transcription in 90+ languages
- keyterm prompting up to 1000 terms
- entity detection
- word-level timestamps
- speaker diarization
- dynamic audio tagging
- smart language detection
- realtime STT via WebSockets with low latency and timestamps

Sources:

- https://elevenlabs.io/docs/overview/capabilities/speech-to-text
- https://elevenlabs.io/docs/api-reference/speech-to-text/convert
- https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime

### Forced Alignment

Use Forced Alignment for reference-guided timing. The endpoint accepts an audio
file and text, then returns character timings, word timings, per-word loss, and
overall loss. It should be used after STT/reference normalization to align the
expected prompt to the child's actual audio.

Sources:

- https://elevenlabs.io/docs/capabilities/forced-alignment
- https://elevenlabs.io/docs/api-reference/forced-alignment/create

### Audio Isolation

Use Audio Isolation when the recording has background noise. The endpoint
expects multipart audio input and removes background noise from speech. It also
supports a low-latency PCM option for 16 kHz mono 16-bit PCM input.

Sources:

- https://elevenlabs.io/docs/capabilities/voice-isolator
- https://elevenlabs.io/docs/api-reference/audio-isolation/convert

### Text To Speech

Use TTS to play prompts to children in a warm voice. Official docs describe
multilingual TTS, streaming, low-latency Flash models, high-quality Multilingual
v2, and expressive Eleven v3.

Sources:

- https://elevenlabs.io/docs/overview/capabilities/text-to-speech
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert

### Pronunciation Dictionaries

Use pronunciation dictionaries for prompt playback, not for scoring the child.
Official docs support IPA and CMU for English and alias tags for other
languages. This helps pronounce Hinglish names, Hindi words in Latin script, and
Indian-English variants in TTS prompts.

Sources:

- https://elevenlabs.io/docs/eleven-api/guides/how-to/text-to-speech/pronunciation-dictionaries
- https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/list

### Sound Effects

Sound Effects can create short reward sounds, but BoloBuddy keeps them disabled
by default to avoid overstimulation and unnecessary cost.

### Agents Platform

Voice Agents can power guided practice conversations. BoloBuddy should not use
agent-level conversational routing for core assessment scoring because scoring
needs deterministic backend-controlled STT, alignment, privacy, and evidence.

## BoloBuddy Product Decision

Production assessment must not use mock STT or mock alignment. The real path is:

1. Capture parent-consented child audio.
2. Optionally run ElevenLabs Audio Isolation.
3. Run ElevenLabs Scribe v2 STT with keyterms, language detection/hints, and word
   timestamps.
4. Run ElevenLabs Forced Alignment against the reference or normalized expected
   text.
5. Run BoloBuddy's deterministic Hinglish NLP, token comparison, scoring,
   insights, and exercises.

Local fixture mode remains only for tests and demos where no child audio or API
key is available.

## Boundaries

ElevenLabs provides transcription, timestamps, isolation, alignment, TTS,
pronunciation control, sound generation, and agents. It does not by itself
provide a clinical cognitive, language, or intelligence diagnosis. BoloBuddy's
report must frame outputs as educational observations and practice guidance, not
IQ, diagnosis, or a measure of the child's worth.
