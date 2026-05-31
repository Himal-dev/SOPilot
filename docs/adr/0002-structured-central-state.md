# ADR-0002: A structured central state store (not chat history)

- Status: Accepted
- Date: 2026-05-29

## Context

Agents that "just stuff everything into the prompt/chat history" are hard to
audit, branch, validate, and resume. SOPilot targets inspections, support,
compliance, and KYC-style workflows where reproducibility and traceability
matter.

## Decision

Use a **structured, versioned central state** (`core/state_runtime/state.py::State`,
a Pydantic model) that every node reads/writes, persisted by the checkpointer.
It carries `goal`, `sop_version`, step progress, `observations`, `evidence`,
`tool_results`, `risks`, `human_overrides`, and `final_output`. Append-only list
fields use the `operator.add` reducer so nodes return only their deltas. List
contents are plain JSON-able dicts (built from typed record models) for robust
serialization across checkpointer backends.

## Options assessment

- **Structured Pydantic state (chosen):** typed, validatable, serializable,
  diffable, branchable; pairs naturally with LangGraph channels/reducers.
- **Chat-history-as-state:** simplest, but opaque, lossy, and unauditable;
  conflates reasoning with the durable record of decisions.
- **External DB/event store only:** durable and auditable, but adds I/O on the
  hot path and a schema-sync burden; we instead let the checkpointer persist the
  state and keep the schema in one place.

## Consequences

- `sop_version` + the evidence ledger make runs reproducible and auditable.
- Keeping the schema as *our* type (not a LangGraph-specific structure) is the
  seam that lets the runtime be swapped.
- We pay a small mapping cost (typed record models → dicts in state) in exchange
  for serialization safety and trivially JSON-able output.
