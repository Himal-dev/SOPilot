# ADR-0003: An append-only evidence ledger

- Status: Accepted
- Date: 2026-05-29

## Context

For inspections, insurance, audits, KYC, compliance, and support, **every
conclusion must point to evidence**. Reviewers need to know which model produced
a claim, how confident it was, and whether a human confirmed it.

## Decision

Maintain an **append-only evidence ledger** (`core/evidence_ledger`). Each
`EvidenceRecord` is `{id, claim, evidence[], model, confidence, human_confirmed,
step_id, created_at}`. Records are created as the agent observes and decides;
output fields and decisions reference ledger entries by id. The ledger is never
mutated or deleted (human confirmation flips a flag on the same record).

## Options assessment

- **Append-only ledger (chosen):** immutable audit trail; cheap to reason about;
  natural fit for the append-reducer state; supports "show me why".
- **Mutable findings object:** simpler to write, but loses history and makes
  audits/regression-tracing impossible.
- **External provenance system (e.g. W3C PROV):** more expressive, heavier; can
  be exported from the ledger later if needed.

## Consequences

- The ledger is the trust/explainability spine; the output generator attaches it
  under `_evidence` and per-field `evidence` references.
- Append-only semantics interact cleanly with checkpointing and resume.
- Confidence on every record enables a future "confidence economy" (budgeting
  attention/cost across models and tools).
