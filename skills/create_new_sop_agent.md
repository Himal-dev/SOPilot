---
name: create_new_sop_agent
description: >
  Scaffold a new SOPilot agent from an SOP without reading all of core/. Use when
  someone wants to turn a checklist, runbook, policy, or inspection procedure into
  a runnable SOPilot agent. Produces examples/<name>/{sop.md, output_schema.json,
  agent_config.yaml, sample_inputs/} and dry-runs it.
---

# Skill: Create a new SOP agent

You can build a complete SOPilot agent by writing **three files + sample inputs**
under `examples/<name>/`. You do **not** need to read `core/` — the contracts you
need are below. Adding an agent never changes `core/`.

## What you produce

```
examples/<name>/
  sop.md                # the procedure
  output_schema.json    # desired output (or set output_schema: suggest)
  agent_config.yaml     # adapters, MCP servers, HITL policy, model/budget
  sample_inputs/        # deterministic cues + MCP catalogs for a no-keys dry-run
  sample_outputs/       # produced by the run
```

## Steps

1. **Gather the SOP and the desired output.** If the user has no output schema,
   set `output_schema: suggest` and let the compiler propose one (it writes
   `suggested_output_schema.json`); then refine it with the user.
2. **Write `sop.md`.** `#` = goal, `##` = sections, `-`/`1.`/`- [ ]` = steps.
   Guide the compiler with inline tags when keywords aren't enough:
   - modality: `[vision]` `[voice]` `[tool]` `[reason]` `[none]`
   - tools: `[tool: name_a, name_b]` (these become `tools_needed`)
   - evidence: `[evidence: ref_a, ref_b]`
   - output fields: `[produces: field_a, field_b]`
   - HITL: `[review: trigger]` (`final_submit`, `doc_rejection`,
     `valuation_change`, `customer_response`, `compliance_fail`)
   - validation: `[validate: expr]` (e.g. `tread_depth_mm >= 2`)
   - branch: `[decision: cond -> step_slug_a | step_slug_b]`
   - confidence floor: `[min_confidence: 0.7]`
   - balanced questioning: `[ask: short summary q; drill-down q]`
3. **Register MCP servers** (if the SOP needs tools) in `agent_config.yaml`
   under `mcp_servers`, each pointing at a `catalog` JSON in `sample_inputs/`
   with `{tools, resources, prompts, responses}`. `responses[tool]` is the canned
   result the stub returns for the dry-run.
4. **Declare HITL points** — usually via `[review: ...]` in the SOP. Set
   `hitl.auto_approve: true` so dry-runs complete; use `reject_triggers` to demo
   a halt.
5. **Add deterministic cues** for vision/voice steps in
   `sample_inputs/<modality>_cues.json`, keyed by **step slug**. Get the exact
   slugs with `python -m sopilot compile examples/<name>`.
6. **Dry-run, iterate, run:**
   ```bash
   python -m sopilot compile examples/<name>     # inspect steps + ids
   python -m sopilot run examples/<name>          # writes sample_outputs/, prints ledger
   python -m sopilot run examples/<name> --interactive
   ```

## Decision guide

**Which adapters?**
- Camera/photos/visual inspection → enable `vision`.
- Hands-free answers, spoken confirmation, interviews → enable `voice`.
- Pure back-office / API work → enable neither (headless, like
  `support_runbook_agent`).

**When to add a HITL point?** Whenever an action is hard to undo or
externally visible: final submit, sending a customer message, rejecting a
document, changing a price/valuation, or flagging compliance. Mark these
`[review: ...]`; leave routine sensing/lookups un-gated.

**Keep voice/questions balanced.** Prefer one summarizing prompt, then drill
down only if needed (`[ask: "Anything pre-existing here?"; "Which panel?"]`).
Don't ask the human to confirm things the vision/tool evidence already settles.

**Confidence economy.** Set `[min_confidence: ...]` on steps where a weak
observation should trigger a recapture/review risk rather than silently passing.

## Acceptance checklist

- [ ] `python -m sopilot compile examples/<name>` shows the steps, modalities,
      `tools_needed`, decision targets (resolving to real step slugs), and
      `human_review_points` you intended.
- [ ] `python -m sopilot run examples/<name>` completes (`status: completed`) with
      `auto_approve: true`, writes `sample_outputs/latest_run.json`, and prints a
      non-empty evidence ledger.
- [ ] At least one HITL checkpoint is hit and resumed (shown under "HITL
      checkpoints"), and `reject_triggers` produces `status: rejected` when set.
- [ ] Every required output-schema field is populated and traces to evidence.
- [ ] The run uses **no API keys** (local compiler fallback + stub adapters/tools).

## Reference docs (only if you need them)

- `docs/how_to_add_new_agent.md` — the long-form version of this skill.
- `docs/state_schema.md` — what the central state holds.
- `docs/tool_connector_contract.md` — how to wire/implement MCP connectors.
- `docs/architecture.md` — the big picture + diagrams.
