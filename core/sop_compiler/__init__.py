"""SOP compiler: turn an SOP into an executable workflow.

Compiles markdown/checklist/policy text into a schema-constrained
:class:`~core.sop_compiler.workflow.CompiledWorkflow`. LLM-driven when an API key
is configured, with a fully deterministic local fallback (markdown/checklist
parsing) so the platform runs with no keys. Can also *suggest* an output schema
when the author provides none.
"""

from core.sop_compiler.compiler import compile_sop, suggest_output_schema
from core.sop_compiler.workflow import (
    CompiledWorkflow,
    DecisionPoint,
    HumanReviewPoint,
    ValidationRule,
    WorkflowStep,
)

__all__ = [
    "compile_sop",
    "suggest_output_schema",
    "CompiledWorkflow",
    "DecisionPoint",
    "HumanReviewPoint",
    "ValidationRule",
    "WorkflowStep",
]
