# SOPilot

**A procedure compiler for voice- and vision-native AI agents.**

SOPilot takes a written operating procedure — a checklist, runbook, policy, or plain markdown SOP — and compiles it into a stateful, evidence-grounded agent that can *see*, *listen*, *act*, and *pause for a human* when the stakes demand it.

If most agent frameworks ask "how do I orchestrate an LLM?", SOPilot asks a different question:

> **What if the SOP itself was the program, and the agent was just its runtime?**

That single shift — treating the procedure as a first-class compilable artifact — changes everything downstream. Adding a new agent stops being a software project and starts being a *document*.

---

## The Thesis

Three observations drove this project:

1. **Real-world expertise lives in SOPs, not prompts.** Mechanics, nurses, inspectors, support engineers, and field technicians already operate from written procedures. The procedure is the product surface. Prompts are implementation detail.

2. **Modern agents are multimodal whether we admit it or not.** A plant triage, a car inspection, a child speech assessment — none of these are text-in / text-out. They are *voice-guided conversations over visual evidence*. Treating voice and vision as bolt-on tools is a category error; they are the primary I/O surface.

3. **Trust comes from evidence, not eloquence.** A confident-sounding LLM answer with no traceable observation behind it is a liability. Every conclusion in a SOPilot run must point back to a piece of evidence — a photo, an utterance, a tool result, a user confirmation — recorded in a ledger.

SOPilot is the architectural consequence of taking those three observations seriously.

---

## What You Get

```text
                  SOP markdown / checklist / policy
                                |
                                v
                       +-----------------+
                       |  sop_compiler   |
                       +-----------------+
                                |
                                v
                       CompiledWorkflow (typed, inspectable)
                                |
                                v
        +----------------- planner (LangGraph StateGraph) -----------------+
        |                                                                 |
        v                  v                  v                  v        |
  vision_adapter     voice_adapter      tool_router        human_review   |
   (see)              (hear/speak)      (MCP-compatible)    (interrupt)   |
        \                  |                  |                  /        |
         \                 v                  v                 /         |
          +----------> evidence_ledger (claim -> evidence) <---+          |
                                |                                         |
                                v                                         |
                       output_generator                                   |
                                |                                         |
                                v                                         |
                Structured, evidence-backed output (JSON/report)          |
                                                                          |
        +-----------------------------------------------------------------+
```

A new agent is a directory, not a codebase:

```text
examples/<agent_name>/
├── sop.md                 # The procedure. The product. The source of truth.
├── output_schema.json     # The contract for downstream consumers.
├── agent_config.yaml      # Adapters, tools, runtime policy, HITL behavior.
└── sample_inputs/         # Deterministic fixtures for local + CI runs.
```

That is the whole authoring surface. There is no `agent.py` to write.

---

## Voice + Vision as First-Class Citizens

Most agent stacks model the world as `messages: list[str]`. SOPilot models it as **observations over modalities**, where text is just one of them.

### Vision Adapter

`core/vision_adapter` is the seam between the planner and "the act of seeing." A plant photo, a damage shot on a rental car, a dashboard warning light — the adapter normalizes them into typed observations that land in state and in the evidence ledger.

- **Stub provider** for deterministic local runs and CI.
- **Live provider** (OpenAI vision today, pluggable tomorrow) for production.
- `require_live: true` makes the run *fail closed* rather than silently fall back to a fixture — because a hallucinated diagnosis is worse than no diagnosis.

### Voice Adapter

`core/voice_adapter` is the dual: the seam between the planner and "the act of listening and speaking." The current live reference uses an ElevenLabs conversational agent driving a guided intake flow on a phone browser.

The key insight: **voice is not a UI skin over a chatbot.** A spoken SOP run is a stateful dialogue with backpressure — the agent asks one question at a time, waits, confirms, and only advances the procedure when the required evidence is in hand. The voice adapter and the planner cooperate on that rhythm; they are not glued together by a prompt.

### Why This Matters

When voice and vision are framework seams rather than tools-in-a-toolbox, three things become possible:

- **The same SOP runs headless, voice-only, vision-only, or fully multimodal.** Channel is a deployment concern, not a procedure concern.
- **Evidence is uniform.** A photo and an utterance both end up in the ledger with the same shape, so the report writer doesn't care which modality produced a fact.
- **Provider swaps are local.** Moving from OpenAI to a local VLM, or from ElevenLabs to a self-hosted voice stack, touches one file.

---

## Design Principles

These are load-bearing, not aspirational:

| Principle | What it means in the codebase |
|---|---|
| **Procedure first** | The SOP is the spec. The compiler — not the developer — turns it into steps, decision points, and review gates. |
| **Typed state, single source of truth** | One Pydantic state object flows through every node. No hidden globals, no scratch dicts, no prompt-stuffed memory. |
| **Evidence by default** | Conclusions and output fields must trace to ledger entries. Unsupported claims are a runtime error, not a vibe. |
| **Human-in-the-loop where it matters** | `human_review` uses a single LangGraph interrupt. The planner owns it. Risky or final actions can pause for approve / edit / reject. |
| **Framework-agnostic seams** | LangGraph imports live in `core/state_runtime` only. Adapters, tool connectors, and report writers depend on SOPilot contracts, not framework internals. Swapping the runtime is mechanical, not a rewrite. |
| **Fail closed on missing evidence** | When `require_live_adapters` is on, missing provider output halts the run with a clear "what to retry" message rather than papering over the gap. |

If you have ever inherited an agent codebase where prompts, tools, state, UI assumptions, and business logic were tangled in one file — these principles are the antidote.

---

## The Mental Model

```text
SOP author writes a procedure.
        |
        |   "compile-time"
        v
sop_compiler produces a CompiledWorkflow:
  - steps with preconditions and required evidence
  - decision points with branching logic
  - tool calls with typed inputs/outputs
  - review checkpoints with HITL policy
  - output schema (explicit or inferred via `suggest`)
        |
        |   "run-time"
        v
planner walks the workflow on a LangGraph StateGraph:
  - reads/writes typed state
  - dispatches to vision_adapter / voice_adapter / tool_router
  - logs every observation into evidence_ledger
  - hits human_review interrupts when the SOP demands a human
  - emits structured output bound to evidence
```

The compile-step is the part most agent frameworks skip. It's also the part that makes a SOPilot agent *inspectable before it runs*:

```bash
python -m sopilot compile examples/car_inspection_agent
```

You get back the executable plan — steps, evidence requirements, decision points, tool calls, review points, output schema — as JSON. Review it like a query plan. Diff it across SOP edits. Stick it in a code review.

---

## The Reference Agents

The repo ships with five agents that span the design space deliberately:

| Agent | Modalities | Why it exists |
|---|---|---|
| `plant_doctor_agent` | Voice + Vision + HITL | The flagship live demo. Voice-guided triage over plant photos, end-to-end on a phone. |
| `car_inspection_agent` | Vision + HITL | Multi-photo evidence flow with explicit review gates. |
| `kids_voice_assessment_agent` | Voice | Stateful conversational SOP with no vision dependency. |
| `support_runbook_agent` | Text + Tools | Classic runbook automation — proves the framework works headless. |
| `rental_move_in_agent` | Vision + Forms | Evidence-heavy structured intake with form-style output. |

Together they answer the question *"is this actually a general framework, or just one app?"* — by being demonstrably different shapes of agent built from the same primitives.

---

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[app]"

# Compile any agent and inspect its executable plan
python -m sopilot compile examples/car_inspection_agent

# Run any agent locally with deterministic fixtures
python -m sopilot run examples/support_runbook_agent
python -m sopilot run examples/plant_doctor_agent --interactive

# Inspect the runtime contract used by browser / voice shells
python -m sopilot manifest examples/plant_doctor_agent

# Run the test suite
pytest
```

Local runs auto-approve review checkpoints (unless `--interactive`), write `sample_outputs/latest_run.json`, and print the evidence ledger. Set `runtime.require_live_adapters: true` in an agent config to flip into production-like behavior where missing provider output halts the run.

---

## Plant Doctor: The Live Reference App

Plant Doctor is the canonical "is this real?" demo: a voice-guided, mobile-first plant triage that collects photos and care history, runs the SOP, and returns a structured care report.

```bash
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE=local-trial-code

uvicorn app.server:app --reload
# Open http://127.0.0.1:8000 on your phone (same Wi-Fi) and talk to it.
```

What makes it interesting:

- The browser shell is **generic** — it consumes the agent manifest (`sopilot manifest`) and renders whatever media, prompts, and HITL policy the SOP declared. Swap the SOP and the same shell runs a different agent.
- The voice flow is a real conversation, not a chatbot transcript: it enforces evidence collection (photo of leaves, photo of soil, watering cadence) before letting the report writer conclude anything.
- If provider evidence is missing, the report stays **incomplete and honest** — telling the user what to retry — rather than inventing a diagnosis.

---

## Deployment

Hosted Plant Doctor runs on a deliberately low-cost AWS serverless shape:

- Static mobile web on **S3**
- FastAPI backend packaged as **AWS Lambda** via Mangum
- **Lambda Function URL** as the API edge
- Invite-code gate (`PLANT_DOCTOR_TRIAL_CODE`) before any provider call
- Per-session JSON logs in **CloudWatch** via `sopilot.session_logging`
- 7-day log retention to keep trial costs predictable

```bash
export AWS_DEFAULT_REGION=ap-south-1
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE="$(cat deploy/aws/plant_doctor_trial_code.txt)"

./deploy/aws/deploy_plant_doctor.sh
```

The deploy script forces `SOPILOT_ENV=production` and disables FastAPI docs. CORS is owned by the Lambda Function URL — keep `PLANT_DOCTOR_CORS_ORIGINS` empty in Lambda env to avoid duplicate `Access-Control-Allow-Origin` headers.

See [`docs/plant-doctor-aws-architecture.md`](docs/plant-doctor-aws-architecture.md) and [`deploy/aws/README.md`](deploy/aws/README.md) for the full picture.

---

## Security Posture (Honest Version)

SOPilot is a **scaffold plus reference demos**, not a hardened SaaS. The current baseline is deliberately conservative for a trial deployment:

**What's in place**

- Secrets via environment variables only; never in source.
- `.env`, deploy metadata, trial codes, SQLite checkpoints, and local reports are gitignored.
- Plant Doctor sits behind an invite code that is not shipped to the browser bundle.
- Optional app-token + invite-code gates in `sopilot.web_runtime`.
- Uploaded media is type- and size-checked before reaching providers.
- Production disables FastAPI docs unless explicitly re-enabled.
- Provider errors to the browser are generic; details stay server-side.

**What I'd close before a wider beta**

- Provider keys into **Secrets Manager / SSM Parameter Store**, not Lambda env vars.
- Replace browser-visible checkpoint paths with **opaque server-side run handles**.
- Restrict CORS to known hosted origins.
- CloudFront in front of S3 for **CSP**, `frame-ancestors`, `X-Content-Type-Options`, and cache control.
- **Rate limiting / AWS WAF** in front of the public Function URL.
- **Dependency + secret scanning** in CI.

Calling these out explicitly is the point — a security model you can read is more valuable than one you have to reverse-engineer from code.

---

## Roadmap

**Near term**

- Promote Plant Doctor run handles from `db_path` plumbing to opaque server-side IDs.
- Provider abstraction layer (OpenAI, ElevenLabs, local/stub, future model-router experiments).
- CI: tests, dependency audit, secret scanning.
- Hosted secrets into AWS Secrets Manager / SSM.

**Medium term**

- Persistent per-subject memory for longitudinal agents (e.g., a plant tracked over months).
- Stronger report evals: JSON validity, evidence grounding, specificity, recovery-guidance quality.
- Production deployment variants: CloudFront + S3 + Lambda, and a container shape for long-running workflows.
- MCP connector examples beyond the stub.

**Long term**

> Treat SOPilot as a **general-purpose agent operating system for domain workflows**: procedure compiler, typed runtime, evidence ledger, human review, tool gateway, and polished voice + vision app shells — across whichever domain has an SOP and a phone in the user's pocket.

---

## Repository Map

```text
app/         Plant Doctor FastAPI server and mobile web UI
core/        SOP compiler, LangGraph runtime, planner, adapters, tools
sopilot/     CLI and reusable app/report/conversation helpers
examples/    Reference agents and fixtures
tests/       Unit, integration, and web-runtime tests
docs/        Architecture, ADRs, deployment notes, design plans
deploy/aws/  AWS deployment scripts and Lambda entrypoints
skills/      SOPilot authoring skills and capability guides
```

---

## Further Reading

- [Architecture](docs/architecture.md)
- [State schema](docs/state_schema.md)
- [Tool connector contract](docs/tool_connector_contract.md)
- [ADRs](docs/adr/)
- [Plant Doctor AWS architecture](docs/plant-doctor-aws-architecture.md)
- [Plant Doctor AWS deploy status](docs/plant-doctor-aws-deploy-status.md)

---

## A Note On Philosophy

It is easy to build an agent demo. It is hard to build an agent you would deploy in front of a stranger, on a phone, over a flaky network, with provider keys that cost money per call, and have it either *do the right thing* or *say honestly that it can't*.

SOPilot is the codebase I wished existed the first three times I built that second kind of agent from scratch. The procedure compiler, the evidence ledger, the voice and vision seams, the fail-closed adapters, the single-source-of-truth state — none of them are clever in isolation. Together they are the difference between a demo and a system you can operate.

If that resonates, the fastest way in is:

```bash
python -m sopilot run examples/plant_doctor_agent --interactive
```
