"""Reference vision adapter (deterministic stub)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.adapters.stub import StubAdapter


class VisionStubAdapter(StubAdapter):
    """Deterministic vision adapter for dry-runs.

    Returns canned, per-step observations from a cue book (typically loaded from
    ``sample_inputs/``). Swap for a VLM-backed adapter by implementing the same
    :class:`~core.adapters.base.Adapter` contract.
    """

    def __init__(
        self,
        cues: Optional[Dict[str, Dict[str, Any]]] = None,
        name: str = "vision",
    ) -> None:
        super().__init__(
            name=name,
            source="vision",
            cues=cues,
            capabilities_=["observe", "act", "capture"],
        )
