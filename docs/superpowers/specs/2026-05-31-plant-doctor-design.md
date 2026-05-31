# Plant Doctor — Live Multimodal SOPilot Demo (Design Spec)

- Date: 2026-05-31
- Status: Approved (pending spec review)
- Owner: SOPilot
- Related: `docs/architecture.md`, `core/adapters/base.py`, `sopilot/runner.py`

## 1. Purpose

Demonstrate the power of the SOPilot scaffold with a simple, real, live
multimodal use case: a single-plant **"Plant Doctor."** A user points a camera
at one plant; the agent runs a plant-care SOP, captures a guided shot list via
**smart in-browser capture**, asks one spoken question, returns an
**evidence-backed care report**, and **speaks** a care plan — pausing for human
approval before finalizing.

The point it proves: adding a real, multimodal, human-in-the-loop agent is
**config + SOP + two real adapters**, with the core contracts, compiler,
planner, and graph left unchanged.

## 2. Goals / Non-goals

Goals:
- Real models: **OpenAI GPT-4o vision** + **ElevenLabs STT/TTS**.
- Live camera with **smart guided capture** (only keep good, on-target frames).
- Real **evidence ledger** (every claim → a captured photo / transcript).
- Real **human-in-the-loop** approve/edit/reject via LangGraph interrupt/resume.
- A **minimal web UI** to run and view it.
- Graceful **stub fallback** when API keys are absent (demo still runs offline).

Non-goals (YAGNI for this demo):
- Multi-plant garden walks (single plant only).
- Fully live mid-graph streaming UI (we use collect-then-run; HITL is still
  real interrupt/resume across two requests).
- Custom-trained vision models (use GPT-4o + off-the-shelf COCO-SSD in-browser).
- Auth, persistence beyond the run, multi-user.

## 3. Scope decisions (locked)

| Decision | Choice |
|---|---|
| Use case | Single-plant Plant Doctor |
| Modalities | Vision + Voice (STT + TTS) |
| Models | OpenAI GPT-4o (vision), ElevenLabs (STT/TTS) |
| Capture trigger | SOP-guided shot list (steady + sharp + on-target) |
| In-browser gating | TF.js COCO-SSD ("potted plant" present) + JS heuristics |
| Architecture | Collect-then-run (Approach 2) with real interrupt/resume HITL |
| Interface | Minimal web UI |

## 4. The SOP

`examples/plant_doctor_agent/sop.md` (compiles with the existing local
compiler — no core changes):

```
# Plant Health Check
## Identify
- Capture the whole plant in frame [vision] [evidence: whole_plant_photo] [produces: plant]
## Examine
- Capture a close-up of the affected leaves or stems [vision] [evidence: closeup_photo] [produces: symptoms] [min_confidence: 0.6]
## Interview
- Ask the gardener about light, watering, and where the plant lives [voice] [produces: care_habits]
## Diagnose
- Determine the likely cause from symptoms and care habits [reason] [produces: diagnosis]
## Care Plan
- Prepare a care plan for the gardener [reason] [produces: care_plan]
## Finalize
- Submit the plant care report [reason] [review: final_submit] [produces: care_report]
```

`examples/plant_doctor_agent/output_schema.json`: an object whose properties
mirror the `produces` fields — `plant`, `symptoms`, `care_habits`, `diagnosis`,
`care_plan`, `care_report` — each carrying `{ value, confidence, evidence }`,
plus `summary` and `completed`. `required`: `summary`, `completed`, `plant`,
`symptoms`, `care_report`.

`examples/plant_doctor_agent/agent_config.yaml`: enables `vision`
(`provider: openai`) and `voice` (`provider: elevenlabs`) adapters, no MCP
servers, `hitl.auto_approve: true` (server overrides to interactive for the UI),
local (no-LLM) compiler.

## 5. Real adapters (new files; existing `Adapter` contract)

Both satisfy `observe` / `act` / `capabilities` exactly, so the planner is
untouched.

- `core/vision_adapter/openai_adapter.py` → `OpenAIVisionAdapter`
  - `observe(request)`: reads the step's image from `request.inputs` (a media
    map keyed by `step_id`), calls **GPT-4o vision** with a step-specific
    instruction derived from `request.instruction`, returns an `Observation`
    with `content={species, common_name, health, symptoms[], severity}`,
    `summary`, `confidence`, `evidence_refs=[image_id]`, `model="gpt-4o"`.
  - On missing key / API failure: raise a typed error the factory catches to
    fall back to the vision stub (logged as a risk).
- `core/voice_adapter/elevenlabs_adapter.py` → `ElevenLabsVoiceAdapter`
  - `observe(request)`: transcribes the recorded answer via **ElevenLabs STT**,
    reusing `ElevenLabsVoiceProvider` from
    `core/kids_voice_assessment/providers.py`. Returns `Observation` with
    `content={transcript, language_code}`, `confidence`, `model="elevenlabs"`.
  - `act(request)`: synthesizes **TTS** for `payload.text`, returns an
    `ActionResult` with the audio URI in `data`.

## 6. Small, generic scaffold extensions

These are general improvements that reinforce the "swap via config" thesis, not
demo special-casing:

1. `AdapterConfig` (in `sopilot/config.py`) gains an optional `provider: str`
   field.
2. `_ADAPTER_FACTORIES` (in `sopilot/runner.py`) becomes a registry keyed by
   `(modality, provider)`, with the deterministic **stub as the default /
   fallback** when no provider is set or no key is present.
3. `run_agent(...)` accepts an optional `media: dict[str, Any]` (per-step image
   bytes/paths and audio) threaded into `Planner.run_inputs`, so real adapters
   receive the actual media. Stub runs ignore it (back-compat).
4. Care-plan **TTS** is produced **after** the run, in the server, by calling
   the voice adapter's `act()` on the finalized care-plan text. (The planner's
   step path only calls `observe`; this is an honest, minimal deviation that
   keeps the SOP and graph unchanged.)

## 7. Backend — `app/server.py` (FastAPI + uvicorn, new optional deps)

Endpoints:
- `POST /api/run` (multipart): guided images (`whole_plant_photo`,
  `closeup_photo`) + recorded audio + meta → builds the media map, runs the
  agent **until the `final_submit` interrupt**, returns
  `{ thread_id, drafted_report, evidence, review_request }`.
- `POST /api/decision`: `{ thread_id, decision: approve|edit|reject, edits? }`
  → **resumes** the real LangGraph interrupt via the SQLite checkpointer,
  returns the finalized report.
- `POST /api/tts`: synthesizes care-plan audio, returns a URL.
- Static file serving for the frontend.

The two-request HITL reuses SOPilot's real `interrupt`/`resume` across requests
(same `thread_id`, persisted by the sqlite checkpointer) — HITL is genuine, not
faked.

Deps isolated under an `app`-scoped optional requirement (e.g.
`pip install -e ".[app]"`): `fastapi`, `uvicorn`, `python-multipart`.

## 8. Frontend — `app/web/` (vanilla JS + TF.js via CDN, no build step)

- **Live camera** via `getUserMedia` with a guided shot-list overlay
  ("① Show me the whole plant" → "② Show me the affected leaves").
- **Smart capture gating:** TF.js **COCO-SSD** confirms a `potted plant`/`plant`
  is in frame; JS heuristics confirm **steady** (frame-difference below a
  threshold) + **sharp** (edge-energy / Laplacian on a canvas). When all pass,
  auto-capture the frame, show a thumbnail, advance the shot list. Otherwise
  show a "move closer / hold steady" hint.
- **Voice:** plays the agent's question (TTS), records the answer via
  `MediaRecorder`.
- **Run view:** steps, captured evidence photos, transcript, diagnosis, and the
  care plan; plays the spoken care plan; **Approve / Edit / Reject** buttons call
  `/api/decision`; final evidence-linked report renders (each claim → its photo).

## 9. Failure cases, cost, latency

- No plant detected / blurry after N seconds → on-screen + spoken nudge.
- Low vision confidence → existing `min_confidence` risk + recapture suggestion.
- Empty / low-confidence STT → prompt to re-record.
- Missing API keys → graceful **stub fallback** (offline demo still completes).
- Cost/latency: GPT-4o on exactly **2 keyframes**, STT **once**, TTS **once**;
  in-browser gating avoids spamming the VLM.

## 10. Explicitly unchanged

Core contracts (`Adapter`, `MCPConnector`, `State`), the SOP compiler, the
planner step logic, and the four-node LangGraph graph all stay as-is.

## 11. Success criteria (verifiable)

1. `python -m sopilot compile examples/plant_doctor_agent` prints a workflow
   with the 6 steps and a `final_submit` review point.
2. `python -m sopilot run examples/plant_doctor_agent` completes end-to-end with
   **stub** adapters (no keys), writing `sample_outputs/latest_run.json` with an
   evidence-backed report.
3. With keys set + `provider` configured, the same run uses GPT-4o + ElevenLabs
   (verified by `model` fields in the evidence ledger).
4. Web UI: capture two gated keyframes, record one answer, see a drafted report,
   approve via the UI, hear the spoken care plan, and view the final
   evidence-linked report.
5. No changes to `core/adapters/base.py`, the planner step logic, or
   `core/state_runtime/graph.py`.

## 12. Open items to resolve in planning

- Exact OpenAI vision call shape (raw `urllib` to stay dependency-light, like
  the ElevenLabs provider, vs. the `openai` SDK).
- Concrete heuristic thresholds for steady/sharp gating (tune during build).
- Whether `care_plan` TTS text is the `summary` or a dedicated field.
