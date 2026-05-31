# SOPilot — SOP + Copilot

A generic, SOP-driven agentic scaffold. Drop in a Standard Operating Procedure
(a checklist, runbook, policy, or markdown) and SOPilot **compiles it into an
executable, stateful agent** that can see, talk, and act through tools/MCP, keeps
a structured "thinking state," records evidence for every conclusion, pauses for
human approval on risky actions, and returns a structured output you defined (or
that SOPilot suggested and you edited).

> **Genericity test:** adding an agent is *config + SOP*, never core code.
> A new agent is just `sop.md` + `output_schema.json` + `agent_config.yaml`
> under `examples/<name>/`. Nothing in `core/` changes.

The runtime is **LangGraph (Python)**: a typed Pydantic central state, persisted
by a checkpointer (SQLite by default), so a run can **interrupt → inspect →
approve/edit/reject → resume**. `core/` stays framework-agnostic at the seams
(our own state schema, adapter contract, and tool-connector contract), so the
runtime could be swapped without touching adapters or SOPs.

## Quickstart (no API keys required)

```bash
cd sopilot
python -m venv .venv && source .venv/bin/activate   # or: uv venv .venv
pip install -e .                                     # or: pip install -r requirements.txt

# Headless tools + HITL runbook:
python -m sopilot run examples/support_runbook_agent

# Voice + vision move-in inspection:
python -m sopilot run examples/rental_move_in_agent

# Vision-centric vehicle inspection (the ported "Jockey"):
python -m sopilot run examples/car_inspection_agent

# Hinglish-first kids voice assessment:
python -m sopilot run examples/kids_voice_assessment_agent

# Live voice + vision plant doctor web UI:
pip install -e ".[app]"
export OPENAI_API_KEY=...                    # required for live vision analysis
export ELEVENLABS_API_KEY=...                # required for private ElevenLabs agent sessions
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...  # or ELEVENLABS_AGENT_ID
export PLANT_DOCTOR_TRIAL_CODE=...           # optional local invite-code gate
uvicorn app.server:app --reload  # open http://127.0.0.1:8000

# Headless Plant Doctor run (stub, no keys):
python -m sopilot run examples/plant_doctor_agent

# Just compile an SOP and print the executable workflow JSON:
python -m sopilot compile examples/car_inspection_agent

# Print app-facing scaffold metadata: media needs, provider readiness, HITL:
python -m sopilot manifest examples/plant_doctor_agent
```

Each `run` compiles the SOP, drives the planner over the state graph using
`sample_inputs/`, **auto-approves** human-review checkpoints in non-interactive
mode (use `--interactive` to approve/edit/reject yourself), writes structured
output to `sample_outputs/latest_run.json`, and prints the evidence ledger.
Everything runs deterministically with **no API keys** via local/stub adapters
and the local SOP-compiler fallback.

For production-like runs, set `runtime.require_live_adapters: true` in
`agent_config.yaml` or `require_live: true` on a specific adapter. The runner
then fails closed instead of silently falling back to fixtures.

App shells can stay generic: `python -m sopilot manifest ...` exposes the media
and interview contract, and `sopilot.media.build_media_map(...)` turns collected
fields into adapter-ready runner input.

Report shells can reuse `sopilot.reporting` to derive required report fields
from the manifest, reject missing/fixture/low-confidence evidence, and return
retry guidance before a domain-specific report writer fills in expert prose.
`sopilot.report_writer` provides the reusable JSON prompt/client hook for that
expert-writing step, and `sopilot.report_view` shapes polished issue/root-cause
recommendation sections for UI display.

For the Plant Doctor web UI, live mode does **not** silently use stub observations:
if real OpenAI/ElevenLabs evidence is unavailable, the report says what failed
instead of filling diagnosis or care-plan fields with placeholders.

## Hosted Plant Doctor Trial

The current hosted Plant Doctor trial runs as a low-cost AWS serverless app:

- Static mobile web app on S3 HTTPS:
  <https://sopilot-plant-doctor-site-746486153317-20260531.s3.ap-south-1.amazonaws.com/index.html>
- FastAPI backend on a Lambda Function URL, packaged with Mangum.
- Invite-only access through `PLANT_DOCTOR_TRIAL_CODE`; the code is not embedded
  in the browser bundle. The deploy writes the current code to the ignored local
  file `deploy/aws/plant_doctor_trial_code.txt`.
- Session-wise JSON logs in CloudWatch via `sopilot.session_logging`; browsers
  send `x-session-id` with auth, voice-session, run, and decision requests.
- Lambda Function URL owns CORS. Keep `PLANT_DOCTOR_CORS_ORIGINS` empty in the
  hosted Lambda env to avoid duplicate `Access-Control-Allow-Origin` headers.

Deploy with:

```bash
export AWS_DEFAULT_REGION=ap-south-1
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE="$(cat deploy/aws/plant_doctor_trial_code.txt)" # preserve existing code
./deploy/aws/deploy_plant_doctor.sh
```

See [Plant Doctor AWS architecture](docs/plant-doctor-aws-architecture.md) and
[Plant Doctor AWS deploy status](docs/plant-doctor-aws-deploy-status.md).

## Guided Conversation Agents

Browser and voice agents can derive their client-tool contract from the same
manifest as the app shell. Use `sopilot.conversation` with
`python -m sopilot manifest examples/<agent>` output:

- `build_guided_tool_names(...)` creates generic state, capture, record-answer,
  and submit names, with app-specific overrides such as Plant Doctor's
  `captureWholePlantPhoto`.
- `build_client_tool_configs(...)` builds ElevenLabs-compatible client tools
  from media requirements, inferred or explicit `RecordTopic` entries, and
  optional structured interview fields.
- `build_guided_instructions(...)` turns manifest media requirements,
  drill-down questions, record topics, and domain/failure/final policies into
  prompt text, including generic retry guidance for missing or low-confidence
  media without restarting the interview.

For Plant Doctor, `GET /api/elevenlabs/setup` exposes the generated prompt and
client tools. Configure those client tools with "wait for response" enabled so
tool results are added to the conversation context.

## The pipeline

```
SOP (md/checklist/policy)
   └─ sop_compiler ──▶ CompiledWorkflow {steps, evidence, decisions, tools,
                       validation_rules, human_review_points, output_schema}
        └─ planner over LangGraph state graph (checkpointed central State)
             ├─ vision_adapter / voice_adapter   (observe / act / capabilities)
             ├─ tool_router (MCP connectors)      (discover + select + call)
             ├─ evidence_ledger                   (append-only claim → evidence)
             └─ human_review (interrupt/resume)   (approve / edit / reject)
        └─ output_generator ──▶ structured output (every field traces to evidence)
```

## Repo layout

```
sopilot/
  core/                 # framework-agnostic seams + LangGraph wiring
    sop_compiler/       # SOP -> executable workflow (LLM-optional, local fallback)
    state_runtime/      # typed central State + LangGraph graph + checkpointer
    planner/            # execute the workflow over the graph
    vision_adapter/     # observe/act/capabilities (stub + OpenAI vision)
    voice_adapter/      # observe/act/capabilities (stub + ElevenLabs voice)
    tool_router/        # MCP connector contract + stub connector + router
    evidence_ledger/    # append-only claim -> evidence records
    human_review/       # HITL via interrupt + auto-approve policy
    output_generator/   # fill/suggest the output schema from state + evidence
  sopilot/              # CLI (python -m sopilot ...)
    scaffold.py         # app-facing manifests + provider readiness policy
    media.py            # upload/transcript fields -> media[step_id]
    conversation.py     # manifest-driven guided voice/browser tool contracts
    reporting.py        # evidence readiness, failures, and retry guidance
    report_writer.py    # reusable JSON report prompt + OpenAI client hook
    report_view.py      # reusable rich-report section/view shaping
    web_runtime.py      # reusable FastAPI CORS/app-token/access-code security
  examples/             # car_inspection / rental_move_in / support_runbook / kids_voice_assessment / plant_doctor
  skills/               # reusable SOPilot build skills and capability guides
  docs/                 # architecture, how-to, state schema, tool contract, ADRs
  tests/                # compiler, expr, end-to-end + HITL reject
```

## Add your own agent

See [`skills/create_new_sop_agent.md`](skills/create_new_sop_agent.md) and
[`docs/how_to_add_new_agent.md`](docs/how_to_add_new_agent.md). The short version:
write `sop.md`, decide on an `output_schema.json` (or `output_schema: suggest`),
wire `agent_config.yaml` (adapters, MCP servers, HITL policy), drop deterministic
cues in `sample_inputs/`, then `python -m sopilot run examples/<name>`.

## Docs

- [Architecture](docs/architecture.md)
- [How to add a new agent](docs/how_to_add_new_agent.md)
- [Scaffold hardening lessons](docs/scaffold-hardening-lessons.md)
- [Plant Doctor AWS architecture](docs/plant-doctor-aws-architecture.md)
- [Plant Doctor AWS deploy status](docs/plant-doctor-aws-deploy-status.md)
- [Plant Doctor mobile trial notes](docs/plant-doctor-mobile-trial.md)
- [State schema](docs/state_schema.md)
- [Tool-connector contract](docs/tool_connector_contract.md)
- [Kids Voice Assessment architecture](docs/kids_voice_assessment_architecture.md)
- [ElevenLabs capabilities for BoloBuddy](docs/elevenlabs_voice_assessment_capabilities.md)
- [AWS deployment scripts](deploy/aws/README.md)
- [ADRs](docs/adr/)
