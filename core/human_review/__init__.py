"""Human-in-the-loop checkpoints via LangGraph ``interrupt``.

High-risk actions (final submit, document rejection, valuation change, customer
response, compliance failure) pause the graph. The runner inspects the
interrupt payload and resumes with an approve/edit/reject decision. A
programmatic :class:`AutoApprovePolicy` lets non-interactive dry-runs complete
while still exercising the real interrupt/resume path.
"""

from core.human_review.review import (
    AutoApprovePolicy,
    ReviewDecision,
    ReviewRequest,
    apply_decision,
)

__all__ = [
    "AutoApprovePolicy",
    "ReviewDecision",
    "ReviewRequest",
    "apply_decision",
]
