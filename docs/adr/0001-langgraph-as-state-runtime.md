# ADR-0001: LangGraph (Python) as the state runtime

- Status: Accepted
- Date: 2026-05-29

## Context

SOPilot needs a runtime for long-running, stateful agent workflows that can
pause for human approval and resume exactly where they left off. The core
requirements are: a typed shared state carried across steps, durable
persistence/checkpointing, interrupt/resume, and a mature Python ecosystem for
LLM extraction, evals, and MCP clients.

## Decision

Adopt **LangGraph (Python)** as the core state runtime. The planner builds graph
nodes; `core/state_runtime/graph.py` wires a `StateGraph` over our Pydantic
`State` and attaches a checkpointer. We keep LangGraph imports confined to two
modules (`state_runtime/graph.py` and the single `interrupt()` call in
`planner/planner.py`) so the rest of `core/` depends only on our own contracts.

## Options assessment

- **LangGraph (chosen):** built for stateful agent graphs; first-class
  checkpointing enables interrupt → inspect → approve/edit/reject → resume;
  streaming, sub-graphs, retries; strong Python LLM/MCP ecosystem.
- **Temporal / Inngest / Restate:** superior for ultra-long durable
  orchestration. Kept as a *possible checkpointer/runner backend*, not the core.
- **Custom reducer kernel:** maximum control, but reinvents persistence,
  interrupts, and tooling. Fallback only.
- **TS / LangGraph.js:** better for browser-native real-time. Only if a use case
  is web-first; examples can ship a thin web client without moving the core.

## Consequences

- We get HITL interrupts and durable resume "for free" via the checkpointer.
- We accept a dependency on LangGraph's API surface (`StateGraph`, `interrupt`,
  `Command`, checkpointers). Confined to two modules to limit blast radius.
- **When we would deviate:** a use case that is dominantly browser real-time with
  no server (→ LangGraph.js), or one needing multi-day durable orchestration with
  strict exactly-once semantics (→ Temporal as the runner, LangGraph for in-step
  reasoning). The framework-agnostic seams (state schema, adapter contract, tool
  contract) make such a swap touch only `state_runtime` + `planner`.
