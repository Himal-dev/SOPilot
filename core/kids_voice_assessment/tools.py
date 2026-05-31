"""Local MCP-ready tools for kids voice assessment.

The connector exposes deterministic tool contracts grouped by server-like name
prefixes. It can be registered with SOPilot's existing ``ToolRouter`` or used
directly in tests.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List

from core.kids_voice_assessment.hinglish_nlp import (
    compare_reference_to_spoken_tokens,
    detect_language_per_token,
    detect_script_per_token,
    generate_code_switch_variants,
    normalize_child_asr_artifacts,
    normalize_hinglish_text,
    tokenize,
    transliterate_devanagari_to_latin,
    transliterate_latin_hindi_to_devanagari,
)
from core.kids_voice_assessment.models import AudioState
from core.kids_voice_assessment.phonemes import (
    g2p_english_ipa,
    g2p_hindi_devanagari,
    g2p_hindi_latin,
    g2p_indian_english_variants,
    get_allowed_allophones,
    map_ipa_to_internal_phone_set,
    map_phone_set_to_child_friendly_label,
)
from core.kids_voice_assessment.providers import MockVoiceProvider
from core.kids_voice_assessment.scoring import (
    calibrate_for_age_band,
    generate_practice_recommendations,
    map_score_to_developmental_level,
    score_completeness,
    score_fluency,
    score_pause_patterns,
    score_target_phoneme,
    score_word_pronunciation,
)
from core.tool_router.contract import (
    PromptSpec,
    ResourceSpec,
    ToolCallResult,
    ToolSpec,
)


class KidsVoiceLocalMCPConnector:
    """In-process MCP-style connector with mock tool implementations."""

    name = "kids_voice_local"

    def __init__(self) -> None:
        self._provider = MockVoiceProvider()
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "normalize_hinglish_text": self._normalize_hinglish_text,
            "detect_script_per_token": self._detect_script_per_token,
            "detect_language_per_token": self._detect_language_per_token,
            "transliterate_latin_hindi_to_devanagari": self._latin_to_dev,
            "transliterate_devanagari_to_latin": self._dev_to_latin,
            "generate_code_switch_variants": self._generate_variants,
            "normalize_child_asr_artifacts": self._normalize_asr,
            "compare_reference_to_spoken_tokens": self._compare_tokens,
            "g2p_english_ipa": lambda a: {"phonemes": g2p_english_ipa(a.get("text", ""))},
            "g2p_indian_english_variants": lambda a: {
                "phonemes": g2p_indian_english_variants(a.get("text", ""))
            },
            "g2p_hindi_devanagari": lambda a: {
                "phonemes": g2p_hindi_devanagari(a.get("text", ""))
            },
            "g2p_hindi_latin": lambda a: {"phonemes": g2p_hindi_latin(a.get("text", ""))},
            "get_allowed_allophones": lambda a: {
                "allophones": get_allowed_allophones(a.get("profile", "indian_english_default"))
            },
            "map_ipa_to_internal_phone_set": lambda a: {
                "phones": map_ipa_to_internal_phone_set(a.get("phones", []))
            },
            "map_phone_set_to_child_friendly_label": lambda a: {
                "label": map_phone_set_to_child_friendly_label(a.get("phone", ""))
            },
            "align_phoneme_sequences": self._align_phonemes,
            "score_word_pronunciation": lambda a: {
                "score": score_word_pronunciation(a.get("status", "matched"), a.get("confidence", 0.7))
            },
            "score_target_phoneme": lambda a: {
                "score": score_target_phoneme(a.get("found", False), a.get("confidence", 0.7))
            },
            "score_fluency": lambda a: {"score": score_fluency(a.get("word_timestamps", []))},
            "score_pause_patterns": lambda a: {
                "score": score_pause_patterns(a.get("word_timestamps", []))
            },
            "score_completeness": lambda a: {
                "score": score_completeness(a.get("matched", 0), a.get("total", 1))
            },
            "calibrate_for_age_band": lambda a: {
                "score": calibrate_for_age_band(a.get("score", 0.0), a.get("age_band", "6-8"))
            },
            "generate_practice_recommendations": self._practice_recs,
            "select_next_prompt": self._select_next_prompt,
            "get_prompt_by_skill": self._get_prompt_by_skill,
            "generate_practice_set": self._generate_practice_set,
            "map_score_to_developmental_level": lambda a: {
                "level": map_score_to_developmental_level(a.get("score", 0.0))
            },
            "recommend_next_activity": self._recommend_next_activity,
            "verify_parental_consent": self._verify_consent,
            "redact_pii": self._redact_pii,
            "create_human_review_case": self._create_review_case,
            "log_audit_event": self._log_audit_event,
            "delete_recording": self._delete_recording,
            "export_parent_report": self._export_parent_report,
            "transcribe_audio": self._transcribe_audio,
            "isolate_voice": self._isolate_voice,
            "forced_align": self._forced_align,
            "synthesize_prompt_audio": self._synthesize_prompt_audio,
            "generate_reward_sound": self._generate_reward_sound,
            "upsert_pronunciation_dictionary_rules": self._upsert_dictionary,
        }

    def list_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name=name,
                server=self.name,
                description=_TOOL_DESCRIPTIONS.get(name, "Kids voice assessment tool."),
                input_schema={"type": "object", "properties": {}},
            )
            for name in self._handlers
        ]

    def list_resources(self) -> List[ResourceSpec]:
        return []

    def list_prompts(self) -> List[PromptSpec]:
        return [
            PromptSpec(
                name="child_safe_hinglish_feedback",
                server=self.name,
                description="Warm child-facing Hinglish feedback template.",
            )
        ]

    def call_tool(self, tool: str, arguments: Dict[str, Any]) -> ToolCallResult:
        handler = self._handlers.get(tool)
        if handler is None:
            return ToolCallResult(
                ok=False,
                tool=tool,
                server=self.name,
                error=f"unknown kids voice tool '{tool}'",
            )
        try:
            return ToolCallResult(
                ok=True,
                tool=tool,
                server=self.name,
                result={"arguments": arguments, **handler(arguments or {})},
            )
        except Exception as exc:  # pragma: no cover - defensive MCP boundary
            return ToolCallResult(
                ok=False,
                tool=tool,
                server=self.name,
                error=str(exc),
            )

    def read_resource(self, uri: str) -> ToolCallResult:
        return ToolCallResult(ok=False, server=self.name, error=f"unknown resource '{uri}'")

    def _normalize_hinglish_text(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"normalized_text": normalize_hinglish_text(args.get("text", ""))}

    def _detect_script_per_token(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tokens = args.get("tokens") or tokenize(args.get("text", ""))
        return {"script_tags": detect_script_per_token(tokens)}

    def _detect_language_per_token(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tokens = args.get("tokens") or tokenize(args.get("text", ""))
        return {"language_tags": detect_language_per_token(tokens)}

    def _latin_to_dev(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"text": transliterate_latin_hindi_to_devanagari(args.get("text", ""))}

    def _dev_to_latin(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"text": transliterate_devanagari_to_latin(args.get("text", ""))}

    def _generate_variants(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "variants": generate_code_switch_variants(
                args.get("reference_text", ""),
                args.get("allowed_variants", {}),
            )
        }

    def _normalize_asr(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"normalized_text": normalize_child_asr_artifacts(args.get("text", ""))}

    def _compare_tokens(self, args: Dict[str, Any]) -> Dict[str, Any]:
        alignment = compare_reference_to_spoken_tokens(
            args.get("reference_tokens", []),
            args.get("spoken_tokens", []),
            allowed_variants=args.get("allowed_variants", {}),
            code_switch_policy=args.get("code_switch_policy", "allow_common_hinglish"),
            assessment_mode=args.get("assessment_mode", "sentence_reading"),
        )
        return {"alignment": [item.model_dump() for item in alignment]}

    def _align_phonemes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        expected = list(args.get("expected", []))
        spoken = list(args.get("spoken", []))
        pairs = []
        matches = 0
        for idx, phone in enumerate(expected):
            got = spoken[idx] if idx < len(spoken) else None
            match = got == phone
            matches += int(match)
            pairs.append({"expected": phone, "spoken": got, "match": match})
        return {"alignment": pairs, "confidence": matches / max(1, len(expected))}

    def _practice_recs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        score = args.get("score", {})
        issues = args.get("issues", [])
        class _Score:
            audio_quality_score = score.get("audio_quality_score", 0.8)
            reference_completeness = score.get("reference_completeness", 0.8)

        return {"recommendations": generate_practice_recommendations(_Score(), issues)}

    def _select_next_prompt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "prompt_id": args.get("prompt_id") or "hinglish_l1_001",
            "reason": "Keep difficulty steady and practice one nearby sentence.",
        }

    def _get_prompt_by_skill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": args.get("skill", "sentence_reading"),
            "prompt_id": "indian_english_l1_001",
        }

    def _generate_practice_set(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "practice_set": [
                "The red ball is under the table.",
                "Mera school bag ready hai.",
            ],
            "count": 2,
        }

    def _recommend_next_activity(self, args: Dict[str, Any]) -> Dict[str, Any]:
        level = args.get("developmental_level", "practicing")
        return {"activity": "slow repeat with one target word", "level": level}

    def _verify_consent(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"consent_verified": bool(args.get("consent_status") == "verified")}

    def _redact_pii(self, args: Dict[str, Any]) -> Dict[str, Any]:
        text = args.get("text", "")
        text = re.sub(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
        text = re.sub(r"\b(?:\+91[- ]?)?\d{10}\b", "[phone]", text)
        return {"redacted_text": text, "pii_redaction_applied": text != args.get("text", "")}

    def _create_review_case(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "review_id": f"review_{args.get('session_id', 'local')}",
            "status": "open",
            "reason": args.get("reason", ["low_model_confidence"]),
        }

    def _log_audit_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"logged": True, "event_type": args.get("event_type", "audit")}

    def _delete_recording(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"recording_id": args.get("recording_id", ""), "deleted": True}

    def _export_parent_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"export_uri": f"mock://reports/{args.get('session_id', 'local')}.json"}

    def _audio_from_args(self, args: Dict[str, Any]) -> AudioState:
        return AudioState(
            recording_id=args.get("recording_id", "mock_recording"),
            raw_audio_uri=args.get("raw_audio_uri", "mock://recording"),
            duration_ms=args.get("duration_ms", 2400),
            volume_score=args.get("volume_score", 0.84),
            noise_score=args.get("noise_score", 0.82),
            vad_speech_detected=args.get("vad_speech_detected", True),
            quality_status=args.get("quality_status", "ok"),
        )

    def _transcribe_audio(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = self._provider.transcribe_audio(self._audio_from_args(args), args)
        return {"transcript": result.model_dump()}

    def _isolate_voice(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = self._provider.isolate_voice(self._audio_from_args(args), args)
        return result.model_dump()

    def _forced_align(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = self._provider.forced_align(
            self._audio_from_args(args),
            args.get("reference_text", ""),
            args,
        )
        return {"alignment": result.model_dump()}

    def _synthesize_prompt_audio(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._provider.synthesize_speech(args.get("text", ""), args).model_dump()

    def _generate_reward_sound(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._provider.generate_sound_effect(args.get("prompt", "soft chime"), args).model_dump()

    def _upsert_dictionary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._provider.create_or_update_pronunciation_dictionary(
            args.get("rules", []), args
        ).model_dump()


_TOOL_DESCRIPTIONS = {
    "normalize_hinglish_text": "Normalize Hinglish, Hindi Latin, Hindi Devanagari, and Indian English text.",
    "detect_script_per_token": "Return latin/devanagari/mixed script tags for each token.",
    "detect_language_per_token": "Return en/hi/hinglish language tags for each token.",
    "generate_code_switch_variants": "Generate prompt-scoped code-switch variants.",
    "compare_reference_to_spoken_tokens": "Align reference and spoken tokens with variant policy.",
    "g2p_indian_english_variants": "Generate Indian English tolerant phoneme variants.",
    "verify_parental_consent": "Verify parent or teacher consent before storing audio.",
    "transcribe_audio": "Fixture-only Scribe-style transcription for SOP dry-runs.",
    "forced_align": "Fixture-only reference-guided alignment for SOP dry-runs.",
    "synthesize_prompt_audio": "Fixture-only prompt playback audio generation.",
}
