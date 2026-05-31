# ADR-0004: Human-in-the-loop via LangGraph interrupts

- Status: Accepted
- Date: 2026-05-29

## Context

High-risk actions must not be taken autonomously: submitting a final report,
rejecting a document, changing a valuation/price, sending a customer response, or
marking a compliance failure. We need to pause mid-run, surface full context to a
human, and resume after approve/edit/reject — without losing run state.

## Decision

Implement HITL with the real **LangGraph `interrupt()`** primitive. The compiled
SOP declares `human_review_points`; the planner's `review` node emits a
`ReviewRequest` (review point, trigger, risk, drafted output, evidence refs, open
risks) via `interrupt(...)`. The checkpointer persists the paused run; the runner
resumes with `Command(resume=ReviewDecision)`. A programmatic
`AutoApprovePolicy` lets non-interactive dry-runs complete while still exercising
the genuine interrupt/resume path (it can also auto-reject by trigger or risk).

## Options assessment

- **LangGraph interrupt + checkpointer (chosen):** durable pause/resume with no
  bespoke state plumbing; the human sees full context; resume is exact.
- **Polling a status flag / external queue:** works headless but reinvents
  durability and loses the "resume exactly here" guarantee.
- **Block the thread on `input()`:** trivial but not durable, not headless, and
  not resumable across restarts.

## Consequences

- The same code path serves interactive humans and automated approvers/tests.
- Review nodes must be side-effect-free *before* the `interrupt()` call, because
  the node re-executes from its start on resume. (Our review node only builds the
  request before interrupting.)
- Rejection sets `status=rejected` and routes to finalize, producing an audited,
  non-submitted output.
