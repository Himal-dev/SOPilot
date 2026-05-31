"""Deterministic Hinglish/code-switch normalization helpers.

The MVP favors transparent rules and prompt-scoped allowed variants over broad
global synonym magic. That keeps reading assessment stricter when needed while
allowing expressive/code-switched speaking to be kinder and more realistic.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from core.kids_voice_assessment.models import (
    HinglishNlpState,
    HinglishToken,
    ModelMetadata,
    WordAlignmentItem,
)


_TOKEN_RE = re.compile(r"[\w\u0900-\u097F']+", re.UNICODE)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_EN_WORDS = {
    "a",
    "after",
    "at",
    "bag",
    "ball",
    "blue",
    "dinner",
    "friend",
    "gave",
    "has",
    "i",
    "is",
    "light",
    "lunch",
    "lunchbox",
    "moon",
    "my",
    "packed",
    "pencil",
    "read",
    "ready",
    "red",
    "robot",
    "saw",
    "school",
    "space",
    "story",
    "stopped",
    "table",
    "the",
    "to",
    "under",
    "we",
    "went",
}

_HI_LATIN_WORDS = {
    "aaj",
    "aasman",
    "bag",
    "chaand",
    "chala",
    "dheere",
    "dost",
    "fir",
    "gaya",
    "gayi",
    "ghar",
    "hai",
    "jana",
    "kahani",
    "ke",
    "khaya",
    "laal",
    "maine",
    "mera",
    "mujhe",
    "neeche",
    "paani",
    "pasand",
    "phir",
    "padi",
    "padhi",
    "school",
    "tiffin",
    "tumne",
    "wali",
    "wala",
}

_LATIN_TO_DEVANAGARI = {
    "mera": "मेरा",
    "bag": "बैग",
    "laal": "लाल",
    "hai": "है",
    "maine": "मैंने",
    "kahani": "कहानी",
    "padhi": "पढ़ी",
    "chaand": "चाँद",
    "aasman": "आसमान",
    "robot": "रोबोट",
    "dheere": "धीरे",
    "chala": "चला",
    "mujhe": "मुझे",
    "school": "स्कूल",
    "jana": "जाना",
}

_DEVANAGARI_TO_LATIN = {v: k for k, v in _LATIN_TO_DEVANAGARI.items()}

_ASR_ARTIFACTS = {
    "um",
    "umm",
    "uh",
    "haan",
    "hmm",
}


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text or "")


def normalize_hinglish_text(text: str) -> str:
    """Lowercase Latin text, preserve Devanagari, remove noisy punctuation."""
    pieces = []
    for token in tokenize(text):
        pieces.append(token.lower() if _LATIN_RE.search(token) else token)
    return " ".join(pieces)


def normalize_child_asr_artifacts(text: str) -> str:
    tokens = []
    prev = None
    for token in normalize_hinglish_text(text).split():
        if token in _ASR_ARTIFACTS:
            continue
        # Collapse immediate repetitions common in child ASR.
        if prev == token:
            continue
        tokens.append(token)
        prev = token
    return " ".join(tokens)


def detect_script_per_token(tokens: Sequence[str]) -> List[str]:
    return [_detect_script(t) for t in tokens]


def detect_language_per_token(tokens: Sequence[str]) -> List[str]:
    return [_detect_language(t) for t in tokens]


def transliterate_latin_hindi_to_devanagari(text: str) -> str:
    return " ".join(_LATIN_TO_DEVANAGARI.get(t.lower(), t) for t in tokenize(text))


def transliterate_devanagari_to_latin(text: str) -> str:
    return " ".join(_DEVANAGARI_TO_LATIN.get(t, t) for t in tokenize(text))


def generate_code_switch_variants(
    reference_text: str, allowed_variants: Dict[str, List[str]]
) -> List[str]:
    """Generate prompt-scoped variants by replacing one token at a time."""
    base = normalize_hinglish_text(reference_text).split()
    variants = {" ".join(base)}
    normalized_map = _normalized_variant_map(allowed_variants)
    for idx, token in enumerate(base):
        for alt in normalized_map.get(token, []):
            candidate = list(base)
            candidate[idx] = alt
            variants.add(" ".join(candidate))
    return sorted(variants)


def analyze_tokens(
    reference_text: str,
    spoken_text: str,
    allowed_variants: Optional[Dict[str, List[str]]] = None,
) -> HinglishNlpState:
    reference_norm = normalize_hinglish_text(reference_text)
    spoken_norm = normalize_child_asr_artifacts(spoken_text)
    ref_tokens = _make_tokens(reference_norm.split(), "reference")
    spoken_tokens = _make_tokens(spoken_norm.split(), "spoken")
    all_tokens = ref_tokens + spoken_tokens
    code_switch_events = _detect_code_switches(spoken_tokens)
    return HinglishNlpState(
        normalized_reference=reference_norm,
        normalized_spoken=spoken_norm,
        reference_tokens=ref_tokens,
        spoken_tokens=spoken_tokens,
        token_language_tags=[
            {"text": t.text, "language": t.language, "source": t.source}
            for t in all_tokens
        ],
        script_tags=[
            {"text": t.text, "script": t.script, "source": t.source}
            for t in all_tokens
        ],
        allowed_reference_variants=allowed_variants or {},
        code_switch_events=code_switch_events,
        metadata=ModelMetadata(
            provider="local",
            model_version="hinglish-rules-v1",
            confidence=0.82,
            uncertainty_notes=[
                "Rule-based language tags are coarse and should be reviewed for edge cases."
            ],
        ),
    )


def compare_reference_to_spoken_tokens(
    reference_tokens: Sequence[str | HinglishToken],
    spoken_tokens: Sequence[str | HinglishToken],
    *,
    allowed_variants: Optional[Dict[str, List[str]]] = None,
    code_switch_policy: str = "allow_common_hinglish",
    assessment_mode: str = "sentence_reading",
) -> List[WordAlignmentItem]:
    """Align reference and spoken tokens with prompt-scoped variant tolerance."""
    ref = [_token_text(t) for t in reference_tokens]
    hyp = [_token_text(t) for t in spoken_tokens]
    variants = _normalized_variant_map(allowed_variants or {})
    n, m = len(ref), len(hyp)
    dp = [[0.0 for _ in range(m + 1)] for _ in range(n + 1)]
    back: List[List[Tuple[str, float]]] = [[("", 0.0) for _ in range(m + 1)] for _ in range(n + 1)]

    miss_cost = 1.0 if assessment_mode == "strict_reading" else 0.72
    insert_cost = 0.85 if assessment_mode == "strict_reading" else 0.45
    subst_cost = 1.0 if assessment_mode == "strict_reading" else 0.72

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + miss_cost
        back[i][0] = ("miss", miss_cost)
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + insert_cost
        back[0][j] = ("insert", insert_cost)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            status, cost = _match_status(
                ref[i - 1], hyp[j - 1], variants, code_switch_policy
            )
            choices = [
                (dp[i - 1][j - 1] + cost, status),
                (dp[i - 1][j] + miss_cost, "miss"),
                (dp[i][j - 1] + insert_cost, "insert"),
            ]
            if status == "substituted":
                choices[0] = (dp[i - 1][j - 1] + subst_cost, "substituted")
            best_value, best_status = min(choices, key=lambda x: x[0])
            dp[i][j] = best_value
            back[i][j] = (best_status, best_value)

    aligned: List[WordAlignmentItem] = []
    i, j = n, m
    while i > 0 or j > 0:
        status = back[i][j][0]
        if status in ("matched", "variant", "substituted"):
            aligned.append(
                WordAlignmentItem(
                    reference=ref[i - 1],
                    spoken=hyp[j - 1],
                    status=status,
                    confidence=0.95 if status == "matched" else 0.78,
                )
            )
            i -= 1
            j -= 1
        elif status == "miss":
            aligned.append(
                WordAlignmentItem(
                    reference=ref[i - 1],
                    status="missed",
                    confidence=0.82,
                )
            )
            i -= 1
        else:
            aligned.append(
                WordAlignmentItem(
                    spoken=hyp[j - 1],
                    status="inserted",
                    confidence=0.78,
                )
            )
            j -= 1
    return list(reversed(aligned))


def _make_tokens(tokens: Sequence[str], source: str) -> List[HinglishToken]:
    return [
        HinglishToken(
            text=t,
            normalized_text=normalize_hinglish_text(t),
            script=_detect_script(t),
            language=_detect_language(t),
            confidence=0.86,
            source=source,  # type: ignore[arg-type]
        )
        for t in tokens
    ]


def _detect_script(token: str) -> str:
    has_devanagari = bool(_DEVANAGARI_RE.search(token))
    has_latin = bool(_LATIN_RE.search(token))
    if has_devanagari and has_latin:
        return "mixed"
    if has_devanagari:
        return "devanagari"
    if has_latin:
        return "latin"
    return "unknown"


def _detect_language(token: str) -> str:
    norm = normalize_hinglish_text(token)
    if _DEVANAGARI_RE.search(token):
        return "hi"
    if norm in _EN_WORDS and norm in _HI_LATIN_WORDS:
        return "hinglish"
    if norm in _HI_LATIN_WORDS:
        return "hi"
    if norm in _EN_WORDS:
        return "en"
    if norm.endswith(("wala", "wali")):
        return "hi"
    return "unknown"


def _detect_code_switches(tokens: Sequence[HinglishToken]) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    prev_lang = ""
    for idx, token in enumerate(tokens):
        lang = token.language
        if prev_lang and lang != "unknown" and lang != prev_lang:
            events.append(
                {
                    "index": str(idx),
                    "from": prev_lang,
                    "to": lang,
                    "token": token.text,
                }
            )
        if lang != "unknown":
            prev_lang = lang
    return events


def _normalized_variant_map(
    allowed_variants: Dict[str, Iterable[str]]
) -> Dict[str, List[str]]:
    normalized: Dict[str, List[str]] = {}
    for key, values in allowed_variants.items():
        key_norm = normalize_hinglish_text(key)
        normalized.setdefault(key_norm, [])
        for value in values:
            value_norm = normalize_hinglish_text(value)
            if value_norm and value_norm not in normalized[key_norm]:
                normalized[key_norm].append(value_norm)
    return normalized


def _token_text(token: str | HinglishToken) -> str:
    if isinstance(token, HinglishToken):
        return token.normalized_text
    return normalize_hinglish_text(token)


def _match_status(
    reference: str,
    spoken: str,
    variants: Dict[str, List[str]],
    policy: str,
) -> Tuple[str, float]:
    if reference == spoken:
        return "matched", 0.0
    variant_allowed = policy in {
        "allow_common_hinglish",
        "allow_semantic_equivalent",
        "free_speech",
        "target_phoneme_only",
    }
    if variant_allowed and spoken in variants.get(reference, []):
        return "variant", 0.1
    if variant_allowed:
        for canonical, alts in variants.items():
            if reference in alts and spoken == canonical:
                return "variant", 0.1
    return "substituted", 1.0
