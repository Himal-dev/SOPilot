"""Small fallback G2P and phoneme scoring helpers.

These rules are intentionally modest. They make the mock demo deterministic and
keep production integration points clear without pretending to be a complete
child-speech phoneme recognizer.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from core.kids_voice_assessment.hinglish_nlp import normalize_hinglish_text
from core.kids_voice_assessment.models import (
    ModelMetadata,
    PhonemeAnalysisResult,
    PhonemeIssue,
)


_EN_G2P = {
    "a": ["ə"],
    "after": ["a", "f", "t", "ər"],
    "bag": ["b", "ae", "g"],
    "ball": ["b", "o", "l"],
    "blue": ["b", "l", "u"],
    "dinner": ["d", "i", "n", "ər"],
    "friend": ["f", "r", "e", "n", "d"],
    "gave": ["g", "e", "v"],
    "is": ["i", "z"],
    "moon": ["m", "u", "n"],
    "my": ["m", "ai"],
    "packed": ["p", "ae", "k", "t"],
    "pencil": ["p", "e", "n", "s", "əl"],
    "read": ["r", "i", "d"],
    "ready": ["r", "e", "d", "i"],
    "red": ["r", "e", "d"],
    "robot": ["r", "o", "b", "o", "t"],
    "saw": ["s", "o"],
    "school": ["s", "k", "u", "l"],
    "space": ["s", "p", "e", "s"],
    "story": ["s", "t", "o", "r", "i"],
    "table": ["t", "e", "b", "əl"],
    "the": ["dh", "ə"],
    "three": ["th", "r", "i"],
    "to": ["t", "u"],
    "under": ["a", "n", "d", "ər"],
    "went": ["w", "e", "n", "t"],
}

_HI_LATIN_G2P = {
    "aaj": ["aa", "j"],
    "chaand": ["ch", "aa", "n", "d"],
    "dost": ["d", "o", "s", "t"],
    "gaya": ["g", "a", "y", "aa"],
    "gayi": ["g", "a", "y", "ii"],
    "hai": ["h", "ai"],
    "jana": ["j", "aa", "n", "aa"],
    "kahani": ["k", "a", "h", "aa", "n", "ii"],
    "khaya": ["kh", "aa", "y", "aa"],
    "laal": ["l", "aa", "l"],
    "maine": ["m", "ai", "n", "e"],
    "mera": ["m", "e", "r", "aa"],
    "mujhe": ["m", "u", "jh", "e"],
    "neeche": ["n", "ii", "ch", "e"],
    "pasand": ["p", "a", "s", "a", "n", "d"],
    "phir": ["ph", "i", "r"],
    "wali": ["w", "aa", "l", "ii"],
    "wala": ["w", "aa", "l", "aa"],
}

_HI_DEV_G2P = {
    "मेरा": ["m", "e", "r", "aa"],
    "बैग": ["b", "ai", "g"],
    "लाल": ["l", "aa", "l"],
    "है": ["h", "ai"],
    "मैंने": ["m", "ai", "n", "e"],
    "कहानी": ["k", "a", "h", "aa", "n", "ii"],
    "पढ़ी": ["p", "a", "dh", "ii"],
    "चाँद": ["ch", "aa", "n", "d"],
    "आसमान": ["aa", "s", "m", "aa", "n"],
    "में": ["m", "e"],
    "रोबोट": ["r", "o", "b", "o", "t"],
    "धीरे": ["dh", "ii", "r", "e"],
    "चला": ["ch", "a", "l", "aa"],
    "मुझे": ["m", "u", "jh", "e"],
    "स्कूल": ["s", "k", "u", "l"],
    "जाना": ["j", "aa", "n", "aa"],
}

_CHILD_LABELS = {
    "r": "rolling r",
    "s": "snake sound",
    "th": "tongue sound",
    "dh": "soft the sound",
    "kh": "airy ka sound",
    "ph": "airy pa sound",
    "aa": "long aa sound",
}


def g2p_english_ipa(text: str) -> Dict[str, List[str]]:
    return {token: _g2p_token(token, _EN_G2P) for token in _tokens(text)}


def g2p_indian_english_variants(text: str) -> Dict[str, List[str]]:
    phones = g2p_english_ipa(text)
    for token, seq in phones.items():
        if token == "school":
            phones[token] = ["i", *seq]
    return phones


def g2p_hindi_latin(text: str) -> Dict[str, List[str]]:
    return {token: _g2p_token(token, _HI_LATIN_G2P) for token in _tokens(text)}


def g2p_hindi_devanagari(text: str) -> Dict[str, List[str]]:
    tokens = [t for t in text.replace("।", " ").split() if t]
    return {token: _HI_DEV_G2P.get(token, _fallback_phone_sequence(token)) for token in tokens}


def get_allowed_allophones(profile: str = "indian_english_default") -> Dict[str, List[str]]:
    base = {
        "v": ["w"],
        "w": ["v"],
        "th": ["t"],
        "dh": ["d"],
        "r": ["ɾ", "r"],
    }
    if profile == "strict_phonics_practice":
        return {}
    if profile == "hindi_phoneme_practice":
        return {"t": ["ṭ"], "d": ["ḍ"], "n": ["ṇ"]}
    return base


def map_ipa_to_internal_phone_set(phones: Iterable[str]) -> List[str]:
    return [p.replace("ə", "uh").replace("ɾ", "r") for p in phones]


def map_phone_set_to_child_friendly_label(phone: str) -> str:
    return _CHILD_LABELS.get(phone, f"{phone} sound")


def analyze_pronunciation(
    reference_text: str,
    spoken_text: str,
    *,
    target_phonemes: Sequence[str] = (),
    accent_tolerance_profile: str = "indian_english_default",
) -> PhonemeAnalysisResult:
    reference = _combined_g2p(reference_text)
    spoken = _combined_g2p(spoken_text)
    allowed = get_allowed_allophones(accent_tolerance_profile)
    issues: List[PhonemeIssue] = []
    total = 0
    matched = 0

    for token, ref_phones in reference.items():
        spoken_phones = spoken.get(token, ref_phones if token in spoken_text.lower() else [])
        total += len(ref_phones)
        matched += _count_phone_matches(ref_phones, spoken_phones, allowed)

    for phone in target_phonemes:
        norm_phone = phone.strip("/")
        if norm_phone and not _phone_seen(norm_phone, spoken.values(), allowed):
            issues.append(
                PhonemeIssue(
                    issue_type="target_sound_needs_practice",
                    sound=norm_phone,
                    child_label=map_phone_set_to_child_friendly_label(norm_phone),
                    confidence=0.58,
                )
            )

    confidence = 0.74 if total else 0.45
    return PhonemeAnalysisResult(
        reference_phonemes=reference,
        spoken_phoneme_hypothesis=spoken,
        phoneme_alignment=[],
        target_phoneme_issues=issues,
        accent_tolerance_profile=accent_tolerance_profile,
        allowed_allophones=allowed,
        phoneme_confidence=confidence,
        metadata=ModelMetadata(
            provider="local",
            model_version="fallback-g2p-v1",
            confidence=confidence,
            uncertainty_notes=[
                "Fallback G2P estimates expected sounds; it is not clinical phoneme recognition."
            ],
        ),
    )


def _combined_g2p(text: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for token in _tokens(text):
        if token in _HI_LATIN_G2P:
            out[token] = _HI_LATIN_G2P[token]
        elif token in _EN_G2P:
            out[token] = _EN_G2P[token]
        else:
            out[token] = _fallback_phone_sequence(token)
    for token, phones in g2p_hindi_devanagari(text).items():
        out[token] = phones
    return out


def _tokens(text: str) -> List[str]:
    return normalize_hinglish_text(text).split()


def _g2p_token(token: str, dictionary: Dict[str, List[str]]) -> List[str]:
    return dictionary.get(token, _fallback_phone_sequence(token))


def _fallback_phone_sequence(token: str) -> List[str]:
    return [ch for ch in token.lower() if ch.isalpha()]


def _count_phone_matches(
    expected: Sequence[str], spoken: Sequence[str], allowed: Dict[str, List[str]]
) -> int:
    count = 0
    for idx, phone in enumerate(expected):
        if idx >= len(spoken):
            continue
        got = spoken[idx]
        if got == phone or got in allowed.get(phone, []):
            count += 1
    return count


def _phone_seen(
    phone: str, spoken_sequences: Iterable[Sequence[str]], allowed: Dict[str, List[str]]
) -> bool:
    accepted = {phone, *allowed.get(phone, [])}
    return any(p in accepted for seq in spoken_sequences for p in seq)
