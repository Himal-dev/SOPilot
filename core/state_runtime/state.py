"""The structured central state -- the agent's "thinking state".

This is **not** chat history. It is a versioned, structured object that every
graph node reads and writes, persisted by the LangGraph checkpointer. Keeping it
as our own Pydantic model (rather than a LangGraph-specific type) is what lets
the runtime be swapped without touching adapters or SOPs.

List fields use the ``operator.add`` reducer so nodes can return *only the new
items* and LangGraph appends them (append-only ledgers, observations, etc.).
List contents are plain JSON-able dicts built from the typed record models in
:mod:`core.evidence_ledger` and below, which keeps every checkpointer backend
(including SQLite) happy and the final output trivially serializable.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """A sense result recorded into state (mirrors adapter Observation)."""

    step_id: str
    source: str
    summary: str = ""
    content: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    evidence_refs: List[str] = Field(default_factory=list)
    model: str = "local-stub"


class ToolResult(BaseModel):
    """The outcome of a tool/MCP call recorded into state."""

    step_id: str
    server: str = ""
    tool: str = ""
    ok: bool = True
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class Risk(BaseModel):
    """A flagged risk (low confidence, failed validation, liveness, etc.)."""

    step_id: str
    kind: str
    severity: str = "warning"
    detail: str = ""


class HumanOverride(BaseModel):
    """Record of a human-in-the-loop decision at a review point."""

    step_id: str
    review_point: str
    decision: str = "approve"  # approve | edit | reject
    edits: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    reviewer: str = "auto"


class State(BaseModel):
    """The central, checkpointed state carried across all graph nodes."""

    goal: str = ""
    sop_version: str = "v1"
    current_step: Optional[str] = None
    completed_steps: Annotated[List[str], operator.add] = Field(default_factory=list)
    pending_steps: List[str] = Field(default_factory=list)
    observations: Annotated[List[Dict[str, Any]], operator.add] = Field(
        default_factory=list
    )
    evidence: Annotated[List[Dict[str, Any]], operator.add] = Field(
        default_factory=list
    )
    tool_results: Annotated[List[Dict[str, Any]], operator.add] = Field(
        default_factory=list
    )
    risks: Annotated[List[Dict[str, Any]], operator.add] = Field(default_factory=list)
    human_overrides: Annotated[List[Dict[str, Any]], operator.add] = Field(
        default_factory=list
    )
    # Accumulated per-field results keyed by output-schema field id.
    step_outputs: Dict[str, Any] = Field(default_factory=dict)
    # Optional domain-specific central state payloads. Examples that need richer
    # typed state can persist their model_dump() here without changing the
    # generic planner contract.
    domain_state: Dict[str, Any] = Field(default_factory=dict)
    final_output: Optional[Dict[str, Any]] = None
    status: str = Field(
        default="running", description="running | completed | rejected."
    )
    log: Annotated[List[str], operator.add] = Field(default_factory=list)
