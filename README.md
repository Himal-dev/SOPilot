# SOPilot

SOPilot turns written operating procedures into executable, evidence-grounded AI
agents. Give it a checklist, runbook, policy, or markdown SOP, and it compiles
that procedure into a stateful workflow that can observe through adapters, call
tools, pause for human review, and return structured output.

The core idea is intentionally simple:

> Adding an agent should be config + SOP, not core-code surgery.

A new agent lives under `examples/<agent_name>/` with:

- `sop.md` — the operating procedure.
- `output_schema.json` — the expected structured output, or `output_schema: suggest`.
- `agent_config.yaml` — adapters, tool servers, runtime policy, and HITL behavior.
- `sample_inputs/` — deterministic fixtures for local runs and tests.

## Why SOPilot Exists

Most agent demos mix prompts, tools, state, UI assumptions, and business logic in
one place. That makes them impressive once and difficult to trust later.

SOPilot separates those concerns:

- **Procedure first:** the SOP is the product surface, and the compiler turns it
  into executable steps.
- **Typed state:** every node reads/writes a central Pydantic state object.
- **Evidence by default:** conclusions and output fields trace back to observed
  evidence.
- **Human review:** risky or final actions can pause the run for approve, edit,
  or reject.
- **Swappable edges:** adapters, MCP/tool connectors, report writers, and web
  shells sit at framework-agnostic seams.

## Architecture

SOPilot uses **LangGraph (Python)** as the state runtime. The LangGraph imports
are intentionally narrow: graph/checkpointer wiring lives in
`core/state_runtime`, and the planner owns the single human-interrupt call. The
rest of the project depends on SOPilot contracts, not LangGraph internals.

```text
SOP markdown / checklist / policy
  -> sop_compiler
  -> CompiledWorkflow
      -> planner over LangGraph StateGraph
          -> adapters observe or act
          -> tool_router calls MCP-compatible connectors
          -> evidence_ledger records claim-to-evidence links
          -> human_review interrupts for approve/edit/reject
      -> output_generator / report writer
      -> structured, evidence-backed output
```

Key modules:

- `core/sop_compiler` compiles SOP text into executable workflow steps.
- `core/state_runtime` defines the central state and LangGraph graph/checkpointer.
- `core/planner` drives plan, execute, review, and finalize nodes.
- `core/vision_adapter` and `core/voice_adapter` provide stub and live providers.
- `core/tool_router` defines the MCP-style tool connector contract.
- `core/evidence_ledger` records the evidence behind observations and outputs.
- `core/human_review` implements HITL review via LangGraph interrupts.
- `sopilot/` exposes the CLI, manifest generation, media mapping, reporting,
  guided conversation contracts, and hosted web runtime helpers.
- `app/` contains the Plant Doctor FastAPI and mobile web demo.

Design references:

- [Architecture](docs/architecture.md)
- [State schema](docs/state_schema.md)
- [Tool connector contract](docs/tool_connector_contract.md)
- [ADRs](docs/adr/)

## Key Workflows

### Compile An SOP

```bash
python -m sopilot compile examples/car_inspection_agent
```

This prints the executable workflow JSON: steps, evidence requirements,
decision points, tool calls, review points, and output schema.

### Run An Agent Locally

```bash
python -m sopilot run examples/support_runbook_agent
python -m sopilot run examples/rental_move_in_agent
python -m sopilot run examples/car_inspection_agent
python -m sopilot run examples/kids_voice_assessment_agent
python -m sopilot run examples/plant_doctor_agent
```

Local runs use deterministic fixtures by default, auto-approve review checkpoints
unless `--interactive` is set, write `sample_outputs/latest_run.json`, and print
the evidence ledger.

For production-like behavior, set `runtime.require_live_adapters: true` in an
agent config or `require_live: true` on a specific adapter. The runner then fails
closed instead of falling back to fixtures.

### Generate App Contracts

```bash
python -m sopilot manifest examples/plant_doctor_agent
```

The manifest exposes media requirements, provider readiness, drill-down
questions, HITL policy, and the output schema. Browser and voice shells use this
to stay generic while each agent remains SOP-specific.

### Plant Doctor Web Demo

Plant Doctor is the current live reference app: a voice-guided, mobile-friendly
plant triage flow that collects photos and care history, runs the SOP, and shows
a structured care report.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[app]"

export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE=local-trial-code

uvicorn app.server:app --reload
```

Open <http://127.0.0.1:8000>.

Live mode requires `OPENAI_API_KEY` for vision/report generation and an
ElevenLabs agent for the guided voice experience. If provider evidence is
missing, the report stays incomplete and explains what to retry instead of
inventing a diagnosis.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[app]"
pytest
```

Use `.env.example` as the non-secret environment template. Do not commit real
keys, invite codes, AWS credentials, generated SQLite checkpoints, local reports,
or deployment metadata.

Useful commands:

```bash
python -m sopilot run examples/plant_doctor_agent --interactive
python -m sopilot compile examples/support_runbook_agent
python -m sopilot manifest examples/kids_voice_assessment_agent
uvicorn app.server:app --reload
```

## Deployment

The current hosted Plant Doctor trial uses a low-cost AWS serverless shape:

- Static mobile web app on S3.
- FastAPI backend packaged as AWS Lambda through Mangum.
- Lambda Function URL for the API.
- Invite-code gate through `PLANT_DOCTOR_TRIAL_CODE`.
- Provider keys stored in Lambda environment variables for the trial.
- Session-wise JSON logs in CloudWatch through `sopilot.session_logging`.
- Seven-day Lambda log retention to control cost.

Deploy:

```bash
export AWS_DEFAULT_REGION=ap-south-1
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE="$(cat deploy/aws/plant_doctor_trial_code.txt)"

./deploy/aws/deploy_plant_doctor.sh
```

Hosted CORS is owned by the Lambda Function URL. Keep
`PLANT_DOCTOR_CORS_ORIGINS` empty in the Lambda environment to avoid duplicate
`Access-Control-Allow-Origin` headers.

The Plant Doctor deploy script sets `SOPILOT_ENV=production` and disables
FastAPI docs endpoints by default. Before a broader beta, move provider secrets
from Lambda environment variables into AWS Secrets Manager or SSM Parameter
Store, restrict CORS to the hosted origin, and put CloudFront in front of S3 for
security headers and cache control.

More detail:

- [Plant Doctor AWS architecture](docs/plant-doctor-aws-architecture.md)
- [Plant Doctor AWS deploy status](docs/plant-doctor-aws-deploy-status.md)
- [AWS deployment scripts](deploy/aws/README.md)

## Security Model

SOPilot treats the repo as a scaffold plus demos, not a fully hardened SaaS yet.
The current baseline:

- Secrets are read from environment variables, never hardcoded into source.
- `.env`, generated deploy metadata, trial-code files, SQLite checkpoints, and
  local reports are gitignored.
- Plant Doctor uses an invite code for trial access. The code is not embedded in
  the browser bundle.
- Optional app-token and invite-code gates live in `sopilot.web_runtime`.
- Uploaded Plant Doctor media is type-checked and size-limited before processing.
- Production Plant Doctor disables FastAPI docs unless explicitly re-enabled.
- Provider errors returned to the browser are generic; detailed error type is
  logged server-side.

Known production gaps to close before wider use:

- Store provider keys in Secrets Manager or SSM instead of Lambda env vars.
- Replace browser-visible checkpoint paths with opaque server-side run handles.
- Restrict CORS to known hosted origins.
- Add CloudFront response headers: CSP, `frame-ancestors`, `X-Content-Type-Options`,
  and tighter caching rules.
- Add rate limiting or AWS WAF for the public Function URL.
- Add dependency scanning and secret scanning in CI.

## Roadmap

Near term:

- Promote Plant Doctor run handles from `db_path` plumbing to opaque server-side
  IDs.
- Add a small provider abstraction for OpenAI, ElevenLabs, local/stub providers,
  and future model-router experiments.
- Add CI for tests, dependency audit, and secret scanning.
- Move hosted secrets to AWS Secrets Manager or SSM.

Medium term:

- Add persistent user/subject memory for longitudinal agents such as Plant Doctor.
- Add stronger report evals: JSON validity, evidence grounding, specificity, and
  recovery guidance quality.
- Add production deployment variants for CloudFront + S3 + Lambda and for a
  container service when long-running workflows need more control.
- Expand MCP connector examples beyond the stub connector.

Long term:

- Treat SOPilot as a reusable agent operating system for domain workflows:
  procedure compiler, typed runtime, evidence ledger, human review, tool gateway,
  and polished app shells.

## Repository Map

```text
app/                 Plant Doctor FastAPI server and mobile web UI
core/                SOP compiler, LangGraph runtime, planner, adapters, tools
sopilot/             CLI and reusable app/report/conversation helpers
examples/            Reference agents and fixtures
tests/               Unit, integration, and web-runtime tests
docs/                Architecture docs, ADRs, deployment notes, plans
deploy/aws/          AWS deployment scripts and Lambda entrypoints
skills/              SOPilot authoring skills and capability guides
```
