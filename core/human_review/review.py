"""Review request/decision models, auto-approve policy, and decision application.

The graph node itself lives in :mod:`core.planner` (so it can close over the
workflow and ledger); this module owns the *contracts* and the pure logic for
deciding and applying a review outcome.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    """The payload surfaced to a human (or the auto-approver) at a checkpoint.

    This is exactly what ``interrupt(...)`` emits, so a UI or CLI can render a
    meaningful approval prompt with full context.
    """

    review_point: str
    trigger: str
    step_id: str
    risk: str = "medium"
    description: str = ""
    drafted_output: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    open_risks: List[Dict[str, Any]] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    """The human/auto resume value for an interrupt."""

    decision: str = Field(default="approve", description="approve | edit | reject.")
    edits: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    reviewer: str = "auto"


class AutoApprovePolicy(BaseModel):
    """A programmatic approver for non-interactive runs.

    Defaults to approving everything (so dry-runs complete), but can be tuned to
    reject above a risk level or for specific triggers, which is useful for
    tests and demos.
    """

    approve: bool = True
    reject_triggers: List[str] = Field(default_factory=list)
    reject_above_risk: Optional[str] = None  # low | medium | high
    reviewer: str = "auto"
    note: str = "Auto-approved by non-interactive policy."

    _RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

    def decide(self, request: ReviewRequest) -> ReviewDecision:
        """Return the decision this policy would make for ``request``."""
        if request.trigger in self.reject_triggers:
            return ReviewDecision(
                decision="reject", reviewer=self.reviewer,
                note=f"Auto-rejected: trigger '{request.trigger}'.",
            )
        if self.reject_above_risk is not None:
            threshold = self._RISK_ORDER.get(self.reject_above_risk, 99)
            if self._RISK_ORDER.get(request.risk, 0) > threshold:
                return ReviewDecision(
                    decision="reject", reviewer=self.reviewer,
                    note=f"Auto-rejected: risk '{request.risk}' over threshold.",
                )
        if not self.approve:
            return ReviewDecision(
                decision="reject", reviewer=self.reviewer,
                note="Auto-policy set to not approve.",
            )
        return ReviewDecision(
            decision="approve", reviewer=self.reviewer, note=self.note
        )


def apply_decision(
    decision: ReviewDecision,
    step_outputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge a review decision's edits into the accumulated step outputs.

    Returns a *new* dict (does not mutate the input). On ``edit``, edited field
    values are merged in; ``approve``/``reject`` leave outputs unchanged here
    (the planner records the override and may halt on reject).
    """
    merged = dict(step_outputs)
    if decision.decision == "edit" and decision.edits:
        for key, value in decision.edits.items():
            merged[key] = value
    return merged
