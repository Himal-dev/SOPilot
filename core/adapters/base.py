"""The adapter contract: ``observe`` / ``act`` / ``capabilities``.

This is one of the framework-agnostic seams. The planner only ever talks to an
:class:`Adapter`; it never imports a concrete model client. Reference stubs in
:mod:`core.vision_adapter` and :mod:`core.voice_adapter` implement this contract
deterministically so the platform runs end-to-end with no API keys.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ObserveRequest(BaseModel):
    """A request for the adapter to sense something for a given step."""

    step_id: str
    instruction: str = Field(
        default="",
        description="What to look for / ask, derived from the SOP step.",
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Step inputs and any media references (paths, urls, ids).",
    )


class Observation(BaseModel):
    """The result of an ``observe`` call.

    ``content`` is adapter-defined structured data (e.g. detected damage, a
    transcribed answer). ``evidence_refs`` point at artifacts the evidence
    ledger can cite.
    """

    step_id: str
    source: str = Field(description="Adapter kind, e.g. 'vision' or 'voice'.")
    content: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_refs: List[str] = Field(default_factory=list)
    model: str = "local-stub"


class ActionRequest(BaseModel):
    """A request for the adapter to act on the world (speak, capture, etc.)."""

    step_id: str
    action: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    ok: bool = True
    detail: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Adapter(Protocol):
    """Contract every perception/actuation adapter must satisfy.

    Implementations should be side-effect-light and deterministic when given the
    same inputs, so runs are replayable. ``name`` identifies the adapter in
    config and evidence records.
    """

    name: str

    def capabilities(self) -> List[str]:
        """Return the capability tags this adapter supports (e.g. ['observe'])."""
        ...

    def observe(self, request: ObserveRequest) -> Observation:
        """Sense the world for a step and return a structured observation."""
        ...

    def act(self, request: ActionRequest) -> ActionResult:
        """Act on the world. Stubs may no-op and return ``ok=True``."""
        ...
