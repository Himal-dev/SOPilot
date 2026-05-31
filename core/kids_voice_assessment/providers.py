"""Voice provider interfaces and mock/ElevenLabs adapters."""

from __future__ import annotations

import json
import mimetypes
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from core.kids_voice_assessment.hinglish_nlp import (
    compare_reference_to_spoken_tokens,
    normalize_hinglish_text,
)
from core.kids_voice_assessment.models import (
    AlignmentResult,
    AudioState,
    ModelMetadata,
    TranscriptResult,
    WordTimestamp,
)


class RealtimeSession(BaseModel):
    session_id: str
    provider: str
    websocket_url: Optional[str] = None
    expires_at: Optional[str] = None


class CleanAudioResult(BaseModel):
    cleaned_audio_uri: str
    provider: str = "mock"
    confidence: float = 0.8
    evidence_references: List[str] = Field(default_factory=list)


class AudioResult(BaseModel):
    audio_uri: str
    provider: str = "mock"
    content_type: str = "audio/mpeg"
    duration_ms: int = 0
    evidence_references: List[str] = Field(default_factory=list)


class DictionaryResult(BaseModel):
    dictionary_id: str
    provider: str = "mock"
    rules_count: int = 0
    evidence_references: List[str] = Field(default_factory=list)


@runtime_checkable
class VoiceProvider(Protocol):
    def transcribe_audio(self, audio: AudioState, options: Dict[str, Any]) -> TranscriptResult:
        ...

    def transcribe_realtime_start(self, options: Dict[str, Any]) -> RealtimeSession:
        ...

    def isolate_voice(self, audio: AudioState, options: Dict[str, Any]) -> CleanAudioResult:
        ...

    def forced_align(
        self, audio: AudioState, reference_text: str, options: Dict[str, Any]
    ) -> AlignmentResult:
        ...

    def synthesize_speech(self, text: str, options: Dict[str, Any]) -> AudioResult:
        ...

    def generate_sound_effect(self, prompt: str, options: Dict[str, Any]) -> AudioResult:
        ...

    def create_or_update_pronunciation_dictionary(
        self, rules: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> DictionaryResult:
        ...


class MockVoiceProvider:
    """Deterministic fixture provider for tests and local demos only."""

    provider = "mock"
    is_fixture = True
    model_version = "mock-voice-v1"

    def transcribe_audio(self, audio: AudioState, options: Dict[str, Any]) -> TranscriptResult:
        reference = options.get("reference_text", "")
        transcript = options.get("mock_transcript") or self._scenario_transcript(reference)
        if audio.quality_status != "ok" or not audio.vad_speech_detected:
            transcript = ""
        timestamps = _timestamps_for(transcript)
        language_code = "hinglish-IN" if _has_code_switch(transcript) else "en-IN"
        confidence = 0.0 if not transcript else options.get("mock_confidence", 0.82)
        return TranscriptResult(
            raw_transcript=transcript,
            normalized_transcript=normalize_hinglish_text(transcript),
            language_code=language_code,
            language_probability=confidence,
            words=normalize_hinglish_text(transcript).split(),
            word_timestamps=timestamps,
            token_logprobs=[-0.12 for _ in timestamps],
            detected_code_switches=[],
            metadata=ModelMetadata(
                provider=self.provider,
                model_version=self.model_version,
                confidence=confidence,
                evidence_references=[audio.recording_id] if audio.recording_id else [],
            ),
        )

    def transcribe_realtime_start(self, options: Dict[str, Any]) -> RealtimeSession:
        return RealtimeSession(
            session_id=options.get("session_id", "mock_realtime"),
            provider=self.provider,
            websocket_url="mock://realtime",
        )

    def isolate_voice(self, audio: AudioState, options: Dict[str, Any]) -> CleanAudioResult:
        uri = audio.cleaned_audio_uri or f"mock://cleaned/{audio.recording_id or 'audio'}"
        return CleanAudioResult(
            cleaned_audio_uri=uri,
            provider=self.provider,
            confidence=0.86,
            evidence_references=[audio.recording_id] if audio.recording_id else [],
        )

    def forced_align(
        self, audio: AudioState, reference_text: str, options: Dict[str, Any]
    ) -> AlignmentResult:
        spoken_text = options.get("spoken_text") or options.get("mock_transcript") or ""
        allowed_variants = options.get("allowed_variants", {})
        alignment = compare_reference_to_spoken_tokens(
            normalize_hinglish_text(reference_text).split(),
            normalize_hinglish_text(spoken_text).split(),
            allowed_variants=allowed_variants,
            code_switch_policy=options.get("code_switch_policy", "allow_common_hinglish"),
            assessment_mode=options.get("assessment_mode", "sentence_reading"),
        )
        matched = [w.reference or "" for w in alignment if w.status in {"matched", "variant"}]
        missed = [w.reference or "" for w in alignment if w.status == "missed" and w.reference]
        inserted = [w.spoken or "" for w in alignment if w.status == "inserted" and w.spoken]
        substituted = [
            {"reference": w.reference or "", "spoken": w.spoken or ""}
            for w in alignment
            if w.status == "substituted"
        ]
        confidence = max(0.2, 1.0 - 0.12 * len(missed) - 0.10 * len(substituted))
        return AlignmentResult(
            provider=self.provider,
            word_alignment=alignment,
            alignment_loss=round(1.0 - confidence, 3),
            matched_words=matched,
            missed_words=missed,
            inserted_words=inserted,
            substituted_words=substituted,
            uncertain_spans=[] if confidence >= 0.55 else [{"reason": "low_alignment_confidence"}],
            metadata=ModelMetadata(
                provider=self.provider,
                model_version="mock-forced-alignment-v1",
                confidence=round(confidence, 3),
                evidence_references=[audio.recording_id] if audio.recording_id else [],
            ),
        )

    def synthesize_speech(self, text: str, options: Dict[str, Any]) -> AudioResult:
        return AudioResult(
            audio_uri=f"mock://tts/{abs(hash(text)) % 100000}",
            provider=self.provider,
            duration_ms=max(600, len(text.split()) * 420),
        )

    def generate_sound_effect(self, prompt: str, options: Dict[str, Any]) -> AudioResult:
        return AudioResult(
            audio_uri=f"mock://sfx/{abs(hash(prompt)) % 100000}",
            provider=self.provider,
            duration_ms=int(options.get("duration_ms", 600)),
        )

    def create_or_update_pronunciation_dictionary(
        self, rules: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> DictionaryResult:
        return DictionaryResult(
            dictionary_id=options.get("dictionary_id", "mock_hinglish_dictionary"),
            provider=self.provider,
            rules_count=len(rules),
        )

    def _scenario_transcript(self, reference: str) -> str:
        normalized = normalize_hinglish_text(reference)
        if normalized == "the red ball is under the table":
            return "the red ball is under table"
        if normalized == "mera school bag ready hai":
            return "mera iskool bag ready hai"
        if normalized == "i went to school phir maine lunch khaya":
            return "I went school phir lunch khaya"
        return reference


class ElevenLabsVoiceProvider:
    """ElevenLabs adapter gated by env vars and privacy config.

    The MVP includes the adapter seam and request shaping. It only makes network
    calls when an API key exists and the caller explicitly allows external
    provider usage.
    """

    provider = "elevenlabs"
    is_fixture = False

    def __init__(self, *, external_provider_allowed: bool = False) -> None:
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        self.stt_model_id = os.environ.get("ELEVENLABS_STT_MODEL_ID", "scribe_v2")
        self.tts_model_id = os.environ.get("ELEVENLABS_TTS_MODEL_ID", "")
        self.child_voice_id = os.environ.get("ELEVENLABS_VOICE_ID_CHILD_FRIENDLY", "")
        self.parent_voice_id = os.environ.get("ELEVENLABS_VOICE_ID_PARENT", "")
        self.enable_logging = _env_bool("ELEVENLABS_ENABLE_LOGGING", False)
        self.use_audio_isolation = _env_bool("ELEVENLABS_USE_AUDIO_ISOLATION", True)
        self.use_forced_alignment = _env_bool("ELEVENLABS_USE_FORCED_ALIGNMENT", True)
        self.use_realtime_stt = _env_bool("ELEVENLABS_USE_REALTIME_STT", False)
        self.external_provider_allowed = external_provider_allowed

    def transcribe_audio(self, audio: AudioState, options: Dict[str, Any]) -> TranscriptResult:
        self._assert_enabled()
        fields = {
            "model_id": options.get("model_id", self.stt_model_id),
            "timestamps_granularity": options.get("timestamps_granularity", "word"),
            "diarize": str(options.get("diarize", False)).lower(),
        }
        if options.get("language_hint") and not options.get("use_language_detection", True):
            fields["language_code"] = options["language_hint"]
        for term in options.get("keyterms", [])[:1000]:
            fields.setdefault("keyterms", [])
            fields["keyterms"].append(term)
        result = self._post_multipart(
            "/v1/speech-to-text",
            file_field="file",
            file_name=_audio_file_name(audio),
            file_bytes=self._read_audio_bytes(audio),
            fields=fields,
        )
        words = result.get("words", [])
        timestamps = [
            WordTimestamp(
                word=w.get("text", ""),
                start_ms=int(float(w.get("start", 0)) * 1000),
                end_ms=int(float(w.get("end", 0)) * 1000),
                confidence=float(_word_confidence(w)),
            )
            for w in words
            if w.get("type", "word") == "word"
        ]
        text = result.get("text", "")
        confidence = _average([w.confidence for w in timestamps]) if timestamps else 0.0
        return TranscriptResult(
            raw_transcript=text,
            normalized_transcript=normalize_hinglish_text(text),
            language_code=result.get("language_code", "unknown"),
            language_probability=float(result.get("language_probability", confidence)),
            words=normalize_hinglish_text(text).split(),
            word_timestamps=timestamps,
            token_logprobs=[],
            metadata=ModelMetadata(
                provider=self.provider,
                model_version=self.stt_model_id,
                confidence=confidence,
                evidence_references=[audio.recording_id],
            ),
        )

    def transcribe_realtime_start(self, options: Dict[str, Any]) -> RealtimeSession:
        self._assert_enabled()
        if not self.use_realtime_stt:
            raise RuntimeError("ElevenLabs realtime STT is disabled by feature flag.")
        return RealtimeSession(
            session_id=options.get("session_id", "elevenlabs_realtime"),
            provider=self.provider,
            websocket_url="wss://api.elevenlabs.io/v1/speech-to-text/realtime",
        )

    def isolate_voice(self, audio: AudioState, options: Dict[str, Any]) -> CleanAudioResult:
        self._assert_enabled()
        if not self.use_audio_isolation:
            return CleanAudioResult(
                cleaned_audio_uri=audio.raw_audio_uri or "",
                provider=self.provider,
                confidence=0.0,
            )
        audio_bytes = self._post_multipart_bytes(
            "/v1/audio-isolation",
            file_field="audio",
            file_name=_audio_file_name(audio),
            file_bytes=self._read_audio_bytes(audio),
            fields={"file_format": options.get("file_format", "other")},
        )
        uri = self._write_output_audio(audio_bytes, "audio_isolation", ".wav")
        return CleanAudioResult(
            cleaned_audio_uri=uri,
            provider=self.provider,
            confidence=0.75,
            evidence_references=[audio.recording_id],
        )

    def forced_align(
        self, audio: AudioState, reference_text: str, options: Dict[str, Any]
    ) -> AlignmentResult:
        self._assert_enabled()
        if not self.use_forced_alignment:
            raise RuntimeError("ElevenLabs forced alignment is disabled by feature flag.")
        result = self._post_multipart(
            "/v1/forced-alignment",
            file_field="file",
            file_name=_audio_file_name(audio),
            file_bytes=self._read_audio_bytes(audio),
            fields={"text": reference_text},
        )
        words = result.get("words", [])
        return AlignmentResult(
            provider=self.provider,
            character_alignment=result.get("characters", []),
            word_alignment=[
                {
                    "reference": w.get("text", ""),
                    "spoken": w.get("text", ""),
                    "status": "matched",
                    "start_ms": int(float(w.get("start", 0)) * 1000),
                    "end_ms": int(float(w.get("end", 0)) * 1000),
                    "confidence": max(0.0, min(1.0, 1.0 - float(w.get("loss", 0.0)))),
                }
                for w in words
            ],
            matched_words=[w.get("text", "") for w in words],
            alignment_loss=float(result.get("loss", 0.0)),
            metadata=ModelMetadata(
                provider=self.provider,
                model_version="elevenlabs-forced-alignment",
                confidence=max(0.0, min(1.0, 1.0 - float(result.get("loss", 0.0)))),
                evidence_references=[audio.recording_id],
            ),
        )

    def synthesize_speech(self, text: str, options: Dict[str, Any]) -> AudioResult:
        self._assert_enabled()
        voice_id = options.get("voice_id") or self.child_voice_id
        audio_bytes = self._post_json_bytes(
            f"/v1/text-to-speech/{voice_id}",
            {
                "text": text,
                "model_id": options.get("model_id", self.tts_model_id),
                "pronunciation_dictionary_locators": options.get(
                    "pronunciation_dictionary_locators", []
                ),
            },
        )
        uri = self._write_output_audio(audio_bytes, "tts", ".mp3")
        return AudioResult(
            audio_uri=uri,
            provider=self.provider,
            duration_ms=0,
        )

    def generate_sound_effect(self, prompt: str, options: Dict[str, Any]) -> AudioResult:
        self._assert_enabled()
        audio_bytes = self._post_json_bytes("/v1/sound-generation", {"text": prompt, **options})
        uri = self._write_output_audio(audio_bytes, "sfx", ".mp3")
        return AudioResult(
            audio_uri=uri,
            provider=self.provider,
            duration_ms=int(options.get("duration_ms", 0)),
        )

    def create_or_update_pronunciation_dictionary(
        self, rules: List[Dict[str, Any]], options: Dict[str, Any]
    ) -> DictionaryResult:
        self._assert_enabled()
        result = self._post_json(
            "/v1/pronunciation-dictionaries",
            {"rules": rules, **options},
        )
        return DictionaryResult(
            dictionary_id=result.get("id", ""),
            provider=self.provider,
            rules_count=len(rules),
        )

    def _assert_enabled(self) -> None:
        if not self.external_provider_allowed:
            raise RuntimeError("External provider usage is blocked by privacy config.")
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is required for ElevenLabs calls.")

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = "https://api.elevenlabs.io" + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "xi-api-key": self.api_key,
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    def _post_json_bytes(self, path: str, payload: Dict[str, Any]) -> bytes:
        url = "https://api.elevenlabs.io" + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "xi-api-key": self.api_key,
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
            return response.read()

    def _post_multipart(
        self,
        path: str,
        *,
        file_field: str,
        file_name: str,
        file_bytes: bytes,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        body, content_type = _multipart_body(
            file_field=file_field,
            file_name=file_name,
            file_bytes=file_bytes,
            fields=fields,
        )
        req = urllib.request.Request(
            "https://api.elevenlabs.io" + path,
            data=body,
            headers={"xi-api-key": self.api_key, "content-type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:  # nosec B310
            text = response.read().decode("utf-8")
        return json.loads(text) if text else {}

    def _post_multipart_bytes(
        self,
        path: str,
        *,
        file_field: str,
        file_name: str,
        file_bytes: bytes,
        fields: Dict[str, Any],
    ) -> bytes:
        body, content_type = _multipart_body(
            file_field=file_field,
            file_name=file_name,
            file_bytes=file_bytes,
            fields=fields,
        )
        req = urllib.request.Request(
            "https://api.elevenlabs.io" + path,
            data=body,
            headers={"xi-api-key": self.api_key, "content-type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:  # nosec B310
            return response.read()

    def _read_audio_bytes(self, audio: AudioState) -> bytes:
        uri = audio.cleaned_audio_uri or audio.raw_audio_uri
        if not uri:
            raise RuntimeError("A real ElevenLabs call requires a local audio file or URL.")
        if uri.startswith("mock://"):
            raise RuntimeError("Mock audio URIs cannot be sent to ElevenLabs.")
        if uri.startswith(("http://", "https://")):
            with urllib.request.urlopen(uri, timeout=30) as response:  # nosec B310
                return response.read()
        return Path(uri).expanduser().read_bytes()

    def _write_output_audio(self, audio: bytes, prefix: str, suffix: str) -> str:
        out_dir = Path(os.environ.get("ELEVENLABS_OUTPUT_DIR", tempfile.gettempdir()))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"bolobuddy_{prefix}_{os.urandom(6).hex()}{suffix}"
        path.write_bytes(audio)
        return str(path)


def _timestamps_for(text: str) -> List[WordTimestamp]:
    timestamps: List[WordTimestamp] = []
    cursor = 120
    for word in normalize_hinglish_text(text).split():
        duration = max(180, min(620, len(word) * 70))
        timestamps.append(
            WordTimestamp(
                word=word,
                start_ms=cursor,
                end_ms=cursor + duration,
                confidence=0.82,
            )
        )
        cursor += duration + 180
    return timestamps


def _has_code_switch(text: str) -> bool:
    tokens = set(normalize_hinglish_text(text).split())
    return bool(tokens & {"phir", "maine", "khaya", "mera", "hai"}) and bool(
        tokens & {"i", "went", "school", "lunch"}
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _average(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _audio_file_name(audio: AudioState) -> str:
    uri = audio.cleaned_audio_uri or audio.raw_audio_uri or "audio.wav"
    if uri.startswith(("http://", "https://")):
        return uri.rsplit("/", 1)[-1] or "audio.wav"
    return Path(uri).name or "audio.wav"


def _word_confidence(word: Dict[str, Any]) -> float:
    if "confidence" in word:
        return float(word["confidence"])
    if "logprob" in word:
        # Convert logprob-ish values into a bounded confidence approximation.
        return max(0.0, min(1.0, 1.0 + float(word["logprob"])))
    return 0.75


def _multipart_body(
    *,
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    fields: Dict[str, Any],
) -> tuple[bytes, str]:
    boundary = f"----bolobuddy{os.urandom(12).hex()}"
    chunks: List[bytes] = []
    for key, value in fields.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is None:
                continue
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                    str(item).encode(),
                    b"\r\n",
                ]
            )
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
