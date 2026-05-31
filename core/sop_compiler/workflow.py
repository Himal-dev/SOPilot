"""Types for the compiled, executable workflow.

This is the contract the planner executes. It mirrors the architecture plan's
compiled-workflow JSON: ``{steps, required_evidence, decision_points,
tools_needed, validation_rules, human_review_points, output_schema}``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Modalities tell the planner which seam to use for a step.
MODALITIES = ("vision", "voice", "tool", "reason", "none")


class WorkflowStep(BaseModel):
    """One executable step of the SOP."""

    id: str
    title: str
    description: str = ""
    modality: str = Field(
        default="reason",
        description="One of vision/voice/tool/reason/none.",
    )
    instruction: str = ""
    required_evidence: List[str] = Field(default_factory=list)
    tools_needed: List[str] = Field(default_factory=list)
    produces: List[str] = Field(
        default_factory=list,
        description="Output-schema field keys this step contributes to.",
    )
    human_review_point: Optional[str] = Field(
        default=None,
        description="Id of a HumanReviewPoint that must clear after this step.",
    )
    summary_template: str = ""
    drilldown_questions: List[str] = Field(
        default_factory=list,
        description="Summary-first -> drill-down question templates, to keep "
        "voice/questioning balanced.",
    )
    min_confidence: float = Field(
        default=0.4,
        description="Below this, the planner records a risk / asks to recapture.",
    )


class DecisionPoint(BaseModel):
    """A branch in the SOP evaluated against state/observations."""

    id: str
    step_id: str
    question: str = ""
    # A safe, restricted expression evaluated against a flat context dict.
    condition: str = ""
    on_true: str = Field(default="", description="Next step id when condition holds.")
    on_false: str = Field(default="", description="Next step id otherwise.")


class ValidationRule(BaseModel):
    """A check applied to a step's evidence/observations."""

    id: str
    applies_to: str = Field(description="Step id this rule validates.")
    expression: str = Field(
        default="",
        description="Restricted boolean expression over the step context.",
    )
    message: str = ""
    severity: str = Field(default="warning", description="info/warning/error.")


class HumanReviewPoint(BaseModel):
    """A high-risk action requiring human approval before proceeding."""

    id: str
    step_id: str = ""
    trigger: str = Field(
        default="final_submit",
        description="e.g. final_submit, doc_rejection, valuation_change, "
        "customer_response, compliance_fail.",
    )
    description: str = ""
    risk: str = Field(default="medium", description="low/medium/high.")


class CompiledWorkflow(BaseModel):
    """The full executable workflow produced by the compiler."""

    goal: str = "complete_sop"
    sop_version: str = "v1"
    source: str = Field(default="local-fallback", description="Compiler path used.")
    steps: List[WorkflowStep] = Field(default_factory=list)
    required_evidence: List[str] = Field(default_factory=list)
    decision_points: List[DecisionPoint] = Field(default_factory=list)
    tools_needed: List[str] = Field(default_factory=list)
    validation_rules: List[ValidationRule] = Field(default_factory=list)
    human_review_points: List[HumanReviewPoint] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)

    def step(self, step_id: str) -> Optional[WorkflowStep]:
        return next((s for s in self.steps if s.id == step_id), None)

    def review_point(self, point_id: str) -> Optional[HumanReviewPoint]:
        return next((p for p in self.human_review_points if p.id == point_id), None)

    def rules_for(self, step_id: str) -> List[ValidationRule]:
        return [r for r in self.validation_rules if r.applies_to == step_id]

    def decisions_for(self, step_id: str) -> List[DecisionPoint]:
        return [d for d in self.decision_points if d.step_id == step_id]
