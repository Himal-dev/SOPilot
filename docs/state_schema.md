# State schema

The central state is our own Pydantic model
(`core/state_runtime/state.py::State`). It is the framework-agnostic seam: every
graph node reads and writes it, and the LangGraph checkpointer persists it so a
run can interrupt and resume exactly where it paused.

List fields use the `operator.add` reducer, so a node returns **only the new
items** and LangGraph appends them (append-only ledgers, observations, etc.).
List contents are plain JSON-able dicts built from the typed record models below,
which keeps every checkpointer backend (including SQLite) happy and makes the
final output trivially serializable.

## `State` fields

| Field | Type | Reducer | Meaning |
|---|---|---|---|
| `goal` | `str` | replace | Slugified SOP goal. |
| `sop_version` | `str` | replace | Compiled SOP version (reproducibility/audit). |
| `current_step` | `str \| None` | replace | Step the planner is on. |
| `completed_steps` | `list[str]` | append | Steps finished, in order. |
| `pending_steps` | `list[str]` | replace | Remaining step ids (decisions may reorder/drop). |
| `observations` | `list[dict]` | append | `Observation` records (sense results). |
| `evidence` | `list[dict]` | append | `EvidenceRecord` entries (the ledger). |
| `tool_results` | `list[dict]` | append | `ToolResult` records (MCP calls). |
| `risks` | `list[dict]` | append | `Risk` records (validation/confidence/etc.). |
| `human_overrides` | `list[dict]` | append | `HumanOverride` records from review points. |
| `step_outputs` | `dict` | replace (merged in-node) | Accumulated per-field results keyed by output-schema field. |
| `domain_state` | `dict` | replace | Optional domain-specific typed state payloads, e.g. kids voice assessment state dumps. |
| `final_output` | `dict \| None` | replace | The generated structured output. |
| `status` | `str` | replace | `running` \| `completed` \| `rejected`. |
| `log` | `list[str]` | append | Human-readable trace of node decisions. |

## Record shapes

`Observation` (`state.py`):

```json
{"step_id": "...", "source": "vision|voice|tool|reason", "summary": "...",
 "content": {}, "confidence": 0.86, "evidence_refs": ["..."], "model": "..."}
```

`EvidenceRecord` (`evidence_ledger/ledger.py`):

```json
{"id": "ev_...", "claim": "...", "evidence": ["front_photo"], "model": "...",
 "confidence": 0.86, "human_confirmed": false, "step_id": "...", "created_at": "..."}
```

`ToolResult` (`state.py`):

```json
{"step_id": "...", "server": "support_stack", "tool": "crm_lookup", "ok": true,
 "arguments": {}, "result": {}, "error": ""}
```

`Risk` (`state.py`):

```json
{"step_id": "...", "kind": "validation_failed|low_confidence|tool_unavailable|...",
 "severity": "info|warning|error", "detail": "..."}
```

`HumanOverride` (`state.py`):

```json
{"step_id": "...", "review_point": "hrp_...", "decision": "approve|edit|reject",
 "edits": {}, "note": "...", "reviewer": "auto|human"}
```

## Checkpointing

`core/state_runtime/graph.py::build_checkpointer` yields a checkpointer:

- `sqlite` (default): durable across process restarts; `path` is a file or
  `:memory:`. A run uses a `thread_id` so its checkpoints are isolated.
- `memory`: in-process only (fast tests).

Because the state is checkpointed, a `human_review` interrupt persists the entire
run. Resuming with `Command(resume=decision)` continues from the paused node with
no recomputation of earlier steps.
