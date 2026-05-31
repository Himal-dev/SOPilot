"""Reference voice adapter (deterministic stub)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.adapters.stub import StubAdapter


class VoiceStubAdapter(StubAdapter):
    """Deterministic voice adapter for dry-runs.

    Returns canned transcribed/structured answers per step from a cue book, and
    treats ``act`` (speaking a prompt) as a no-op acknowledgement. Swap for an
    STT/TTS-backed adapter by implementing the same
    :class:`~core.adapters.base.Adapter` contract.
    """

    def __init__(
        self,
        cues: Optional[Dict[str, Dict[str, Any]]] = None,
        name: str = "voice",
    ) -> None:
        super().__init__(
            name=name,
            source="voice",
            cues=cues,
            capabilities_=["observe", "act", "speak", "transcribe"],
        )
