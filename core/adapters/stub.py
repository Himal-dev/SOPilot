"""A deterministic reference adapter shared by the vision/voice stubs.

It reads a "cue book" -- a mapping of ``step_id`` -> canned observation -- that
examples ship in ``sample_inputs/``. This lets dry-runs produce meaningful,
replayable output with no model calls. A real adapter would instead call a VLM
or STT/TTS service while satisfying the same :class:`~core.adapters.base.Adapter`
contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.adapters.base import (
    ActionRequest,
    ActionResult,
    Observation,
    ObserveRequest,
)


class StubAdapter:
    """Deterministic adapter backed by a per-step cue book."""

    def __init__(
        self,
        name: str,
        source: str,
        cues: Optional[Dict[str, Dict[str, Any]]] = None,
        capabilities_: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self._source = source
        self._cues: Dict[str, Dict[str, Any]] = cues or {}
        self._capabilities = capabilities_ or ["observe", "act"]

    def capabilities(self) -> List[str]:
        return list(self._capabilities)

    def observe(self, request: ObserveRequest) -> Observation:
        cue = self._cues.get(request.step_id, {})
        summary = cue.get("summary") or (
            f"[{self._source} stub] {request.instruction or request.step_id}"
        )
        return Observation(
            step_id=request.step_id,
            source=self._source,
            content=cue.get("content", {}),
            summary=summary,
            confidence=float(cue.get("confidence", 0.55)),
            evidence_refs=list(cue.get("evidence_refs", [])),
            model=f"{self.name}:stub",
        )

    def act(self, request: ActionRequest) -> ActionResult:
        # Stubs do not touch the world; they acknowledge the action so the
        # planner can record that an action occurred.
        return ActionResult(
            ok=True,
            detail=f"[{self._source} stub] acted '{request.action}' for "
            f"{request.step_id}",
            data=request.payload,
        )
