# How to add a new agent

Adding an agent is **config + SOP only**. Nothing in `core/` changes. An agent is
three files (plus deterministic sample inputs) under `examples/<name>/`:

```
examples/<name>/
  sop.md                # the SOP, in markdown/checklist form
  output_schema.json    # your desired output (or set output_schema: suggest)
  agent_config.yaml     # wiring: adapters, MCP servers, HITL policy, model/budget
  sample_inputs/        # deterministic cues / MCP catalogs for dry-runs
  sample_outputs/       # produced by `run` (latest_run.json)
```

## 1. Write `sop.md`

Use `#` for the goal/title, `##` for sections, and `-`/`1.`/`- [ ]` list items
for steps. The compiler infers each step's modality, evidence, tools, review
points, decisions, and validation from keywords — and you can be explicit with
inline tags:

| Tag | Effect |
|---|---|
| `[vision]` `[voice]` `[tool]` `[reason]` `[none]` | force the step modality |
| `[tool: name_a, name_b]` | tool step using these `tools_needed` |
| `[evidence: ref_a, ref_b]` | required evidence refs |
| `[produces: field_a, field_b]` | output-schema fields this step fills |
| `[review: trigger]` | human-review point (e.g. `final_submit`, `customer_response`) |
| `[validate: expr]` | validation rule (e.g. `tread_depth_mm >= 2`) |
| `[decision: cond -> step_a \| step_b]` | branch: take `step_a` if `cond` else `step_b` |
| `[min_confidence: 0.7]` | below this, the planner flags a risk |
| `[ask: q1; q2]` | summary-first drill-down questions (keeps voice balanced) |

Decision/validation expressions are evaluated by a **safe** mini-evaluator
(`core/planner/expr.py`): names resolve from the step's observation/tool content,
comparisons/`and`/`or`/`not`/membership are supported, unknown names are `None`.
Decision branch targets must match the **slug** of the target step (the slug is
derived from the step's text). Run `python -m sopilot compile examples/<name>` to
see the generated step ids.

## 2. Decide on an output schema

- Provide `output_schema.json` (draft-07 JSON Schema). Top-level properties named
  after a step's `produces` field get filled with `{value, confidence, evidence}`.
  `summary` and `completed` are computed automatically.
- Or set `output_schema: suggest` in the config. The compiler proposes a schema
  from your steps and writes it to `suggested_output_schema.json` for you to edit.

## 3. Wire `agent_config.yaml`

```yaml
name: my_agent
sop: sop.md
output_schema: output_schema.json     # or: suggest
adapters:
  vision: { enabled: true, cues: sample_inputs/vision_cues.json }
  voice:  { enabled: true, cues: sample_inputs/voice_cues.json }
mcp_servers:
  - { name: my_stack, type: stub, catalog: sample_inputs/mcp_my_stack.json }
hitl:
  auto_approve: true                  # non-interactive completion
  reject_triggers: []                 # e.g. ["customer_response"] to demo a halt
model:
  compiler: { use_llm: false }        # deterministic local compiler by default
```

## 4. Provide deterministic dry-run inputs

- **Adapter cues** (`sample_inputs/*_cues.json`): map `step_id -> {summary,
  confidence, content, evidence_refs}`. Stub adapters return these so runs are
  replayable with no model calls.
- **MCP catalogs** (`sample_inputs/mcp_*.json`): `{tools, resources, prompts,
  responses}`. `responses[tool_name]` is the canned result the stub returns.

## 5. Dry-run, iterate, run

```bash
python -m sopilot compile examples/my_agent     # inspect the workflow + step ids
python -m sopilot manifest examples/my_agent    # inspect app-facing media/provider needs
python -m sopilot run examples/my_agent          # auto-approve HITL, write output
python -m sopilot run examples/my_agent --interactive   # approve/edit/reject yourself
```

Check the printed evidence ledger and `sample_outputs/latest_run.json`. Iterate
on the SOP wording/tags until the steps, evidence, and review points are right.

## Going to production

- Put all app-facing collection requirements in the SOP. Use `[evidence: ...]`
  for upload/capture fields and `[ask: q1; q2]` for sequential voice questions.
  `python -m sopilot manifest examples/my_agent` exposes these as
  `media_requirements`, so a web app or voice guide does not need hardcoded flow
  state.
- Use `sopilot.media.build_media_map(...)` to convert app fields, uploads, and
  transcripts into runner `media` keyed by compiled step id. This keeps compiled
  slugs out of app code.
- For guided voice/browser agents, use `sopilot.conversation` instead of
  hand-writing client tools. Build names with `build_guided_tool_names(...)`,
  passing app-specific state/submit/record names or capture overrides when the
  product needs branded names. Then pass the manifest and names to
  `build_client_tool_configs(...)` with inferred or explicit `RecordTopic`
  values and structured interview fields, and to
  `build_guided_instructions(...)` with any domain, failure, or final-response
  policy. The generated instructions preserve collected answers during media
  retries so weak photos do not restart the whole interview.
- For app-facing reports, use `sopilot.reporting` before writing domain prose.
  `report_field_specs_from_manifest(...)` derives required report inputs from
  manifest media requirements, and `build_report_readiness(...)` returns
  collected fields, missing/demo/low-confidence failures, next steps, and
  retry media fields. Keep domain-specific explanation and recommendations in
  your app report builder, but let the scaffold own the reliability gate.
- For LLM-written reports, use `sopilot.report_writer` for the reusable JSON
  prompt/client plumbing. Define a `ReportPromptSpec` with the domain expert
  role, task, output contract, evidence policy, and style rules; then call
  `build_report_prompt_payload(...)` and `write_openai_json_report(...)`.
  Keep product-specific normalization/view shaping local.
- For rich UI reports, use `sopilot.report_view` to shape the common section
  skeleton: subject summary, issue, root cause, recommendations, monitoring,
  escalation, confidence, evidence, warnings, and optional product aliases.
  Keep only domain-specific labels and extra fields in the app layer.
- Swap a stub adapter for a real VLM/STT-TTS adapter implementing the same
  `Adapter` contract (`observe`/`act`/`capabilities`).
- Set `runtime.require_live_adapters: true` or per-adapter `require_live: true`
  when production must fail closed instead of falling back to fixtures.
- For hosted demos that should submit immediately, set
  `runtime.auto_finalize_on_start: true` or call `start_run(...,
  auto_finalize=True)` from the app server.
- Use `sopilot.web_runtime.install_api_security(...)` for CORS and an optional
  `x-app-token` gate instead of rebuilding that middleware per app.
- Swap a stub MCP connector for a real one implementing `MCPConnector`.
- Set `model.compiler.use_llm: true` (and the relevant API-key env var) to use
  the LLM compiler path; it falls back to the local parser if unavailable.
- Use the `sqlite` checkpointer with a file path for durable, resumable runs.
