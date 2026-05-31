# Plant Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live, multimodal "Plant Doctor" demo to SOPilot — a single-plant agent that captures a guided photo shot-list, asks a spoken question, and returns an evidence-backed, human-approved care report — using real OpenAI vision + ElevenLabs voice, with a minimal web UI.

**Architecture:** Reuse the SOPilot scaffold unchanged at its core (Adapter/State contracts, compiler, planner, 4-node graph). Add (1) a new `examples/plant_doctor_agent/` (SOP + schema + config), (2) two real adapters satisfying the existing `Adapter` contract, (3) small generic runner extensions for provider selection + media threading, and (4) a thin FastAPI server + vanilla-JS frontend implementing collect-then-run with real LangGraph interrupt/resume for HITL.

**Tech Stack:** Python 3.10+, LangGraph, Pydantic, FastAPI + uvicorn (new, optional `[app]` extra), OpenAI GPT-4o (HTTP), ElevenLabs (reusing `core/kids_voice_assessment/providers.py`), TensorFlow.js COCO-SSD (CDN, browser), vanilla JS.

---

## Conventions (read first)

- Work from the repo root: `/Users/himal.mangla/token26-hackathon/sopilot`.
- Run tests with: `python -m pytest -q` (or a single test as shown per task).
- The venv is at `.venv`; activate with `source .venv/bin/activate`.
- Every code task is TDD: write the failing test, run it red, implement, run it green, commit.
- Commit messages use Conventional Commits (`feat:`, `test:`, `chore:`, `docs:`).
- **Do NOT** edit: `core/adapters/base.py`, `core/planner/planner.py` step logic, or `core/state_runtime/graph.py`. If a task seems to require it, stop and flag.
- No secrets in code. Real model calls read `OPENAI_API_KEY` / `ELEVENLABS_API_KEY` from the environment only.

---

## File Structure

Create:
- `examples/plant_doctor_agent/sop.md` — the SOP.
- `examples/plant_doctor_agent/output_schema.json` — output contract.
- `examples/plant_doctor_agent/agent_config.yaml` — wiring (providers, HITL).
- `examples/plant_doctor_agent/sample_inputs/vision_cues.json` — stub cue book.
- `examples/plant_doctor_agent/sample_inputs/voice_cues.json` — stub cue book.
- `core/vision_adapter/openai_adapter.py` — `OpenAIVisionAdapter`.
- `core/voice_adapter/elevenlabs_adapter.py` — `ElevenLabsVoiceAdapter`.
- `app/__init__.py`, `app/server.py` — FastAPI server (start/resume/tts).
- `app/web/index.html`, `app/web/app.js`, `app/web/styles.css` — frontend.
- `tests/test_plant_doctor_example.py`
- `tests/test_adapter_registry.py`
- `tests/test_openai_vision_adapter.py`
- `tests/test_elevenlabs_voice_adapter.py`
- `tests/test_plant_doctor_server.py`

Modify:
- `core/vision_adapter/__init__.py` — export `OpenAIVisionAdapter`.
- `core/voice_adapter/__init__.py` — export `ElevenLabsVoiceAdapter`.
- `sopilot/config.py` — add `provider` to `AdapterConfig`.
- `sopilot/runner.py` — provider-aware adapter registry; `media` threading; `start_run` / `resume_run`.
- `pyproject.toml` — add optional `[app]` extra; register new packages.
- `README.md` — add Plant Doctor + web UI instructions.

---

## Task 1: Plant Doctor example (SOP + schema + config), runs on stubs

**Files:**
- Create: `examples/plant_doctor_agent/sop.md`
- Create: `examples/plant_doctor_agent/output_schema.json`
- Create: `examples/plant_doctor_agent/agent_config.yaml`
- Create: `examples/plant_doctor_agent/sample_inputs/vision_cues.json`
- Create: `examples/plant_doctor_agent/sample_inputs/voice_cues.json`
- Test: `tests/test_plant_doctor_example.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plant_doctor_example.py
"""The Plant Doctor example compiles and runs end-to-end on stub adapters."""

from pathlib import Path

from core.sop_compiler import compile_sop
from sopilot.config import load_agent_config
from sopilot.runner import run_agent

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def test_plant_doctor_compiles_to_expected_shape():
    config = load_agent_config(AGENT)
    sop_text = config.resolve(config.sop).read_text()
    wf = compile_sop(sop_text)
    step_ids = [s.id for s in wf.steps]
    # 6 SOP bullets -> 6 steps.
    assert len(wf.steps) == 6
    # The finalize step declares a human review point.
    assert any(p.trigger == "final_submit" for p in wf.human_review_points)
    # Vision + voice modalities both appear.
    modalities = {s.modality for s in wf.steps}
    assert "vision" in modalities and "voice" in modalities


def test_plant_doctor_stub_run_completes_with_evidence():
    result = run_agent(AGENT, checkpointer_backend="memory")
    assert result.state.status == "completed"
    assert result.review_events  # final_submit HITL fired
    assert len(result.state.evidence) >= 3
    assert result.state.final_output is not None
    assert "care_report" in result.state.final_output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plant_doctor_example.py -q`
Expected: FAIL (`FileNotFoundError: missing agent_config.yaml` or directory missing).

- [ ] **Step 3: Create the SOP**

```markdown
<!-- examples/plant_doctor_agent/sop.md -->
# Plant Health Check

A single-plant care SOP. The agent captures a guided shot list (whole plant, then
a close-up of affected leaves), asks the gardener one spoken question about care
habits, diagnoses the likely cause, prepares a care plan, and pauses for approval
before submitting. Every finding is backed by a photo or the spoken answer.

## Identify
- Capture the whole plant in frame [vision] [evidence: whole_plant_photo] [produces: plant]

## Examine
- Capture a close-up of the affected leaves or stems [vision] [evidence: closeup_photo] [produces: symptoms] [min_confidence: 0.6]

## Interview
- Ask the gardener about light, watering, and where the plant lives [voice] [produces: care_habits]

## Diagnose
- Determine the likely cause from the symptoms and care habits [reason] [produces: diagnosis]

## Care Plan
- Prepare a care plan for the gardener [reason] [produces: care_plan]

## Finalize
- Submit the plant care report for the gardener [reason] [review: final_submit] [produces: care_report]
```

- [ ] **Step 4: Create the output schema**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "plant_care_report",
  "type": "object",
  "properties": {
    "summary": {"type": "string", "description": "Overall plant health summary."},
    "completed": {"type": "boolean"},
    "plant": {"type": "object", "description": "Species/identity findings + photo evidence."},
    "symptoms": {"type": "object", "description": "Observed symptoms + close-up evidence."},
    "care_habits": {"type": "object", "description": "Gardener's spoken care habits."},
    "diagnosis": {"type": "object", "description": "Likely cause(s) with confidence."},
    "care_plan": {"type": "object", "description": "Recommended care actions."},
    "care_report": {"type": "object", "description": "Approved, submitted report record."}
  },
  "required": ["summary", "completed", "plant", "symptoms", "care_report"]
}
```

- [ ] **Step 5: Create the agent config**

```yaml
# examples/plant_doctor_agent/agent_config.yaml
name: plant_doctor_agent
description: >
  Live single-plant "Plant Doctor". Captures a guided photo shot-list (vision),
  asks the gardener about care habits (voice), diagnoses the likely cause, and
  pauses before submitting an evidence-backed care report.
sop: sop.md
sop_version: v1
output_schema: output_schema.json

adapters:
  vision:
    enabled: true
    provider: openai
    cues: sample_inputs/vision_cues.json
  voice:
    enabled: true
    provider: elevenlabs
    cues: sample_inputs/voice_cues.json

mcp_servers: []

hitl:
  auto_approve: true
  reject_triggers: []
  reject_above_risk: null
  reviewer: auto

model:
  compiler:
    use_llm: false
    api_key_env: OPENAI_API_KEY
  max_steps: 50
  budget_usd: 0.0
```

- [ ] **Step 6: Create the stub cue books** (so offline/no-key runs are meaningful)

```json
{
  "capture_the_whole_plant_in_frame": {
    "summary": "Healthy-looking potted pothos; some lower-leaf yellowing.",
    "confidence": 0.78,
    "content": {"species": "Epipremnum aureum", "common_name": "Pothos", "health": "fair", "symptoms": ["lower-leaf yellowing"], "severity": "mild"},
    "evidence_refs": ["whole_plant_photo"]
  },
  "capture_a_close_up_of_the_affected_leaves_or_stems": {
    "summary": "Close-up shows yellowing with green veins on older leaves.",
    "confidence": 0.72,
    "content": {"symptoms": ["interveinal yellowing", "soft stems"], "severity": "mild"},
    "evidence_refs": ["closeup_photo"]
  }
}
```

```json
{
  "ask_the_gardener_about_light_watering_and_where_the_plant_lives": {
    "summary": "I water it every day and it sits in low indoor light.",
    "confidence": 0.8,
    "content": {"transcript": "I water it every day and it sits in low indoor light.", "watering": "daily", "light": "low indoor"},
    "evidence_refs": ["care_habits_audio"]
  }
}
```

Note: the cue keys are the compiler's slugs for each bullet (lowercased, non-alphanumerics → `_`). If a key does not match, the stub still returns a generic observation — the test only requires completion + evidence, not exact cue content.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_plant_doctor_example.py -q`
Expected: PASS (2 passed). The stub run works because, with no API keys set, the provider-aware factory (Task 2) is not yet present — at this point `vision`/`voice` still resolve to stubs via the existing `_ADAPTER_FACTORIES`, and the unknown `provider` key is ignored until Task 2 adds it to the model. If `provider` causes a validation error now, proceed to Task 2 first, then re-run this task's tests.

- [ ] **Step 8: Commit**

```bash
git add examples/plant_doctor_agent tests/test_plant_doctor_example.py
git commit -m "feat: add plant_doctor_agent example (SOP + schema + config)"
```

---

## Task 2: Provider field + provider-aware adapter registry (stub fallback)

**Files:**
- Modify: `sopilot/config.py` (add `provider` to `AdapterConfig`)
- Modify: `sopilot/runner.py` (`_build_adapters` becomes provider-aware)
- Test: `tests/test_adapter_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adapter_registry.py
"""Provider-aware adapter selection with deterministic stub fallback."""

from pathlib import Path

from sopilot.config import load_agent_config
from sopilot.runner import _build_adapters
from core.vision_adapter import VisionStubAdapter
from core.voice_adapter import VoiceStubAdapter

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def test_falls_back_to_stub_when_no_api_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    config = load_agent_config(AGENT)
    adapters = _build_adapters(config)
    assert isinstance(adapters["vision"], VisionStubAdapter)
    assert isinstance(adapters["voice"], VoiceStubAdapter)


def test_selects_real_adapters_when_keys_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    config = load_agent_config(AGENT)
    adapters = _build_adapters(config)
    assert adapters["vision"].__class__.__name__ == "OpenAIVisionAdapter"
    assert adapters["voice"].__class__.__name__ == "ElevenLabsVoiceAdapter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adapter_registry.py -q`
Expected: FAIL (`provider` unknown field, or fallback returns stub when keys present because real adapters don't exist yet).

- [ ] **Step 3: Add `provider` to `AdapterConfig`**

In `sopilot/config.py`, change `AdapterConfig`:

```python
class AdapterConfig(BaseModel):
    enabled: bool = True
    # Which adapter implementation to use: "stub" (default), "openai", "elevenlabs".
    provider: str = "stub"
    # Path (relative to the agent dir) to a per-step cue book for the stub.
    cues: Optional[str] = None
```

- [ ] **Step 4: Make `_build_adapters` provider-aware in `sopilot/runner.py`**

Add imports near the top:

```python
import os

from core.vision_adapter import OpenAIVisionAdapter, VisionStubAdapter
from core.voice_adapter import ElevenLabsVoiceAdapter, VoiceStubAdapter
```

Replace the existing `_ADAPTER_FACTORIES` and `_build_adapters` with:

```python
_STUB_FACTORIES = {
    "vision": VisionStubAdapter,
    "voice": VoiceStubAdapter,
}


def _build_adapter(modality: str, adapter_cfg, config: "AgentConfig"):
    """Pick a real adapter when its provider + API key are available, else stub."""
    cues = _load_cues(config, adapter_cfg)
    provider = (getattr(adapter_cfg, "provider", "stub") or "stub").lower()

    if modality == "vision" and provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        return OpenAIVisionAdapter(name="vision")
    if modality == "voice" and provider == "elevenlabs" and os.environ.get("ELEVENLABS_API_KEY"):
        return ElevenLabsVoiceAdapter(name="voice")

    stub = _STUB_FACTORIES.get(modality)
    return stub(cues=cues) if stub else None


def _build_adapters(config: AgentConfig) -> Dict[str, Any]:
    adapters: Dict[str, Any] = {}
    for modality, adapter_cfg in config.adapters.items():
        if not adapter_cfg.enabled:
            continue
        adapter = _build_adapter(modality, adapter_cfg, config)
        if adapter is not None:
            adapters[modality] = adapter
    return adapters
```

Note: `OpenAIVisionAdapter` / `ElevenLabsVoiceAdapter` are created in Tasks 4–5. To keep this task green in isolation, also create minimal placeholder classes now if they don't exist — but the recommended order is to do Tasks 4 and 5 first, then this task. If you implement in plan order, temporarily stub the imports by completing Task 4 and Task 5 before running Step 5 here.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_adapter_registry.py tests/test_plant_doctor_example.py tests/test_runner.py -q`
Expected: PASS (existing runner tests still pass — stub fallback preserves old behavior).

- [ ] **Step 6: Commit**

```bash
git add sopilot/config.py sopilot/runner.py tests/test_adapter_registry.py
git commit -m "feat: provider-aware adapter registry with stub fallback"
```

---

## Task 3: Thread per-step `media` into the run

**Files:**
- Modify: `sopilot/runner.py` (`run_agent` accepts `media`; passed into `Planner.run_inputs`)
- Test: `tests/test_adapter_registry.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_adapter_registry.py`:

```python
def test_media_is_threaded_into_run_inputs():
    from core.sop_compiler import compile_sop
    from core.planner.planner import Planner

    wf = compile_sop("# T\n## Do\n- Take a photo [vision] [produces: x]\n")

    captured = {}

    class RecordingAdapter:
        name = "vision"
        def capabilities(self): return ["observe"]
        def observe(self, request):
            captured["inputs"] = request.inputs
            from core.adapters.base import Observation
            return Observation(step_id=request.step_id, source="vision", confidence=0.9)
        def act(self, request):
            from core.adapters.base import ActionResult
            return ActionResult()

    planner = Planner(wf, adapters={"vision": RecordingAdapter()},
                      run_inputs={"agent": "t", "media": {"take_a_photo": {"image_id": "p1"}}})
    planner.execute_node(planner.plan_node(planner.initial_state()) and planner.initial_state())
    # Re-run cleanly to capture inputs:
    state = planner.initial_state()
    state.current_step = wf.steps[0].id
    planner.execute_node(state)
    assert "media" in captured["inputs"]
    assert captured["inputs"]["media"]["take_a_photo"]["image_id"] == "p1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adapter_registry.py::test_media_is_threaded_into_run_inputs -q`
Expected: FAIL only if `run_agent` lacks `media`; but this test drives `Planner` directly, which already forwards `run_inputs` into `observe`. Run it — if it PASSES already, that confirms the planner seam works; still add the `run_agent` plumbing below so the server can pass media.

- [ ] **Step 3: Add `media` to `run_agent`**

In `sopilot/runner.py`, change the `run_agent` signature and the planner construction:

```python
def run_agent(
    agent_dir: str | Path,
    *,
    interactive: bool = False,
    checkpointer_backend: str = "sqlite",
    db_path: Optional[str] = None,
    output_path: Optional[str] = None,
    media: Optional[Dict[str, Any]] = None,
    on_event=None,
) -> RunResult:
```

And where the `Planner(...)` is constructed:

```python
    planner = Planner(
        workflow=workflow,
        adapters=adapters,
        tool_router=tool_router,
        run_inputs={"agent": config.name, "media": media or {}},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_adapter_registry.py tests/test_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sopilot/runner.py tests/test_adapter_registry.py
git commit -m "feat: thread per-step media into agent run inputs"
```

---

## Task 4: OpenAIVisionAdapter (real GPT-4o vision, injectable HTTP)

**Files:**
- Create: `core/vision_adapter/openai_adapter.py`
- Modify: `core/vision_adapter/__init__.py`
- Test: `tests/test_openai_vision_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openai_vision_adapter.py
"""OpenAIVisionAdapter parses a GPT-4o JSON response into an Observation."""

import base64

from core.adapters.base import ObserveRequest
from core.vision_adapter import OpenAIVisionAdapter


def _fake_chat_fn(payload):
    # Simulate the OpenAI chat-completions JSON response shape.
    import json
    content = json.dumps({
        "species": "Epipremnum aureum",
        "common_name": "Pothos",
        "health": "fair",
        "symptoms": ["interveinal yellowing"],
        "severity": "mild",
        "confidence": 0.81,
        "summary": "Pothos with mild yellowing on older leaves.",
    })
    return {"choices": [{"message": {"content": content}}]}


def test_observe_parses_vision_json():
    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=_fake_chat_fn)
    img = base64.b64encode(b"fake-jpeg-bytes").decode()
    req = ObserveRequest(
        step_id="capture_the_whole_plant_in_frame",
        instruction="Capture the whole plant in frame",
        inputs={"media": {"capture_the_whole_plant_in_frame": {
            "image_b64": img, "image_id": "whole_plant_photo", "mime": "image/jpeg"}}},
    )
    obs = adapter.observe(req)
    assert obs.source == "vision"
    assert obs.model == "gpt-4o"
    assert obs.confidence == 0.81
    assert obs.content["common_name"] == "Pothos"
    assert "whole_plant_photo" in obs.evidence_refs


def test_observe_without_image_returns_low_confidence():
    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=_fake_chat_fn)
    req = ObserveRequest(step_id="s1", instruction="look", inputs={"media": {}})
    obs = adapter.observe(req)
    assert obs.confidence == 0.0
    assert "no image" in obs.summary.lower()


def test_capabilities_and_act():
    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=_fake_chat_fn)
    assert "observe" in adapter.capabilities()
    from core.adapters.base import ActionRequest
    res = adapter.act(ActionRequest(step_id="s1", action="noop"))
    assert res.ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_openai_vision_adapter.py -q`
Expected: FAIL (`ImportError: cannot import name 'OpenAIVisionAdapter'`).

- [ ] **Step 3: Implement the adapter**

```python
# core/vision_adapter/openai_adapter.py
"""Real vision adapter backed by OpenAI GPT-4o (chat completions, vision).

Satisfies the framework-agnostic :class:`~core.adapters.base.Adapter` contract.
The HTTP call is injectable (``chat_fn``) so the adapter is unit-testable with no
network. The image for a step is passed in ``ObserveRequest.inputs['media']``,
keyed by ``step_id``, as ``{"image_b64": ..., "image_id": ..., "mime": ...}``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from core.adapters.base import (
    ActionRequest,
    ActionResult,
    Observation,
    ObserveRequest,
)

_SYSTEM = (
    "You are a careful plant-health vision assistant. Look at the image and the "
    "instruction, and respond ONLY with a compact JSON object with keys: "
    "species, common_name, health, symptoms (array of short strings), severity "
    "(one of: none, mild, moderate, severe), confidence (0..1 number), and "
    "summary (one short sentence). If unsure, lower the confidence."
)


class OpenAIVisionAdapter:
    """GPT-4o-backed vision adapter."""

    def __init__(
        self,
        *,
        name: str = "vision",
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        chat_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.name = name
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._chat_fn = chat_fn or self._default_chat_fn

    def capabilities(self) -> List[str]:
        return ["observe", "act", "capture"]

    def observe(self, request: ObserveRequest) -> Observation:
        media = (request.inputs or {}).get("media", {}) or {}
        entry = media.get(request.step_id) or {}
        image_b64 = entry.get("image_b64")
        if not image_b64:
            return Observation(
                step_id=request.step_id,
                source="vision",
                summary="No image provided for this step.",
                confidence=0.0,
                model=self.model,
            )

        mime = entry.get("mime", "image/jpeg")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.instruction or request.step_id},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime};base64,{image_b64}"}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
            "temperature": 0,
        }
        try:
            response = self._chat_fn(payload)
            content = response["choices"][0]["message"]["content"]
            data = json.loads(content)
        except Exception as exc:  # network/parse failure -> low-confidence, no crash
            return Observation(
                step_id=request.step_id,
                source="vision",
                summary=f"Vision call failed: {exc}",
                confidence=0.0,
                model=self.model,
            )

        confidence = float(data.get("confidence", 0.5) or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        image_id = entry.get("image_id", request.step_id)
        return Observation(
            step_id=request.step_id,
            source="vision",
            content=data,
            summary=data.get("summary", "") or request.instruction,
            confidence=confidence,
            evidence_refs=[image_id],
            model=self.model,
        )

    def act(self, request: ActionRequest) -> ActionResult:
        return ActionResult(ok=True, detail=f"vision noop '{request.action}'")

    def _default_chat_fn(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
            return json.loads(resp.read().decode("utf-8"))
```

- [ ] **Step 4: Export from the package**

Replace `core/vision_adapter/__init__.py` with:

```python
"""Vision adapter: see the world for a step.

Ships a deterministic reference stub plus a real GPT-4o adapter. Both satisfy
:class:`~core.adapters.base.Adapter`.
"""

from core.vision_adapter.adapter import VisionStubAdapter
from core.vision_adapter.openai_adapter import OpenAIVisionAdapter

__all__ = ["VisionStubAdapter", "OpenAIVisionAdapter"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_openai_vision_adapter.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add core/vision_adapter/openai_adapter.py core/vision_adapter/__init__.py tests/test_openai_vision_adapter.py
git commit -m "feat: add OpenAIVisionAdapter (GPT-4o, injectable HTTP)"
```

---

## Task 5: ElevenLabsVoiceAdapter (real STT + TTS, reusing the provider)

**Files:**
- Create: `core/voice_adapter/elevenlabs_adapter.py`
- Modify: `core/voice_adapter/__init__.py`
- Test: `tests/test_elevenlabs_voice_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_elevenlabs_voice_adapter.py
"""ElevenLabsVoiceAdapter transcribes (observe) and synthesizes (act)."""

from core.adapters.base import ActionRequest, ObserveRequest
from core.kids_voice_assessment.providers import MockVoiceProvider
from core.voice_adapter import ElevenLabsVoiceAdapter


def test_observe_transcribes_via_provider():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    req = ObserveRequest(
        step_id="ask_the_gardener",
        instruction="Ask about light and watering",
        inputs={"media": {"ask_the_gardener": {
            "audio_path": "/tmp/answer.wav",
            "recording_id": "rec1",
            "options": {"mock_transcript": "I water it every day in low light"},
        }}},
    )
    obs = adapter.observe(req)
    assert obs.source == "voice"
    assert obs.model.startswith("elevenlabs") or obs.model == "mock"
    assert "water" in obs.content["transcript"].lower()
    assert obs.confidence > 0.0
    assert "rec1" in obs.evidence_refs


def test_observe_without_audio_returns_low_confidence():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    req = ObserveRequest(step_id="s1", instruction="ask", inputs={"media": {}})
    obs = adapter.observe(req)
    assert obs.confidence == 0.0
    assert "no audio" in obs.summary.lower()


def test_act_synthesizes_speech():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    res = adapter.act(ActionRequest(step_id="s1", action="speak",
                                    payload={"text": "Here is your care plan."}))
    assert res.ok is True
    assert res.data.get("audio_uri")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_elevenlabs_voice_adapter.py -q`
Expected: FAIL (`ImportError: cannot import name 'ElevenLabsVoiceAdapter'`).

- [ ] **Step 3: Implement the adapter**

```python
# core/voice_adapter/elevenlabs_adapter.py
"""Real voice adapter: ElevenLabs STT (observe) + TTS (act).

Wraps the existing :class:`~core.kids_voice_assessment.providers.ElevenLabsVoiceProvider`
so the heavy HTTP/multipart plumbing is reused. The provider is injectable so the
adapter is unit-testable with the in-repo ``MockVoiceProvider``.

Per-step audio is passed in ``ObserveRequest.inputs['media']`` keyed by ``step_id``
as ``{"audio_path": ..., "recording_id": ..., "options": {...}}``.
"""

from __future__ import annotations

from typing import Any, List, Optional

from core.adapters.base import (
    ActionRequest,
    ActionResult,
    Observation,
    ObserveRequest,
)
from core.kids_voice_assessment.models import AudioState


class ElevenLabsVoiceAdapter:
    """ElevenLabs-backed voice adapter (STT + TTS)."""

    def __init__(self, *, name: str = "voice", provider: Optional[Any] = None) -> None:
        self.name = name
        if provider is None:
            from core.kids_voice_assessment.providers import ElevenLabsVoiceProvider

            provider = ElevenLabsVoiceProvider(external_provider_allowed=True)
        self._provider = provider

    def capabilities(self) -> List[str]:
        return ["observe", "act", "speak", "transcribe"]

    def observe(self, request: ObserveRequest) -> Observation:
        media = (request.inputs or {}).get("media", {}) or {}
        entry = media.get(request.step_id) or {}
        audio_path = entry.get("audio_path")
        if not audio_path:
            return Observation(
                step_id=request.step_id,
                source="voice",
                summary="No audio provided for this step.",
                confidence=0.0,
                model="elevenlabs",
            )

        recording_id = entry.get("recording_id", request.step_id)
        audio = AudioState(
            recording_id=recording_id,
            raw_audio_uri=audio_path,
            vad_speech_detected=True,
            quality_status="ok",
        )
        options = entry.get("options", {}) or {}
        result = self._provider.transcribe_audio(audio, options)
        transcript = result.raw_transcript or ""
        confidence = float(result.language_probability or 0.0)
        model = getattr(self._provider, "provider", "elevenlabs")
        return Observation(
            step_id=request.step_id,
            source="voice",
            content={"transcript": transcript, "language_code": result.language_code},
            summary=transcript or "No speech detected.",
            confidence=confidence,
            evidence_refs=[recording_id],
            model=model,
        )

    def act(self, request: ActionRequest) -> ActionResult:
        text = (request.payload or {}).get("text", "")
        if not text:
            return ActionResult(ok=False, detail="No text to synthesize.")
        result = self._provider.synthesize_speech(text, request.payload or {})
        return ActionResult(
            ok=True,
            detail="Synthesized care-plan speech.",
            data={"audio_uri": result.audio_uri, "provider": result.provider},
        )
```

- [ ] **Step 4: Export from the package**

Replace `core/voice_adapter/__init__.py` with:

```python
"""Voice adapter: ask/answer and speak prompts for a step.

Ships a deterministic reference stub plus a real ElevenLabs adapter (STT + TTS).
Both satisfy the :class:`~core.adapters.base.Adapter` contract.
"""

from core.voice_adapter.adapter import VoiceStubAdapter
from core.voice_adapter.elevenlabs_adapter import ElevenLabsVoiceAdapter

__all__ = ["VoiceStubAdapter", "ElevenLabsVoiceAdapter"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_elevenlabs_voice_adapter.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add core/voice_adapter/elevenlabs_adapter.py core/voice_adapter/__init__.py tests/test_elevenlabs_voice_adapter.py
git commit -m "feat: add ElevenLabsVoiceAdapter (STT observe + TTS act)"
```

---

## Task 6: Two-phase run helpers — `start_run` / `resume_run`

**Files:**
- Modify: `sopilot/runner.py` (add `start_run`, `resume_run`, extract `_build_planner`)
- Test: `tests/test_plant_doctor_server.py` (server tests; here add a runner-level test)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plant_doctor_server.py
"""Two-phase HITL run: start until interrupt, then resume to finalize."""

from pathlib import Path

from sopilot.runner import start_run, resume_run

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def test_start_run_pauses_at_review(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    started = start_run(AGENT, media={}, db_path=db)
    assert started["status"] == "interrupted"
    assert started["review_request"]["trigger"] == "final_submit"
    assert started["thread_id"]
    assert started["drafted_output"]  # drafted care_report fields present


def test_resume_run_approves_and_finalizes(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    started = start_run(AGENT, media={}, db_path=db)
    final = resume_run(
        AGENT, thread_id=started["thread_id"],
        decision={"decision": "approve", "reviewer": "ui"}, db_path=db,
    )
    assert final["status"] == "completed"
    assert "care_report" in final["final_output"]
    assert final["evidence"]


def test_resume_run_reject_halts(tmp_path):
    db = str(tmp_path / "cp.sqlite")
    started = start_run(AGENT, media={}, db_path=db)
    final = resume_run(
        AGENT, thread_id=started["thread_id"],
        decision={"decision": "reject", "reviewer": "ui", "note": "needs work"},
        db_path=db,
    )
    assert final["status"] == "rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plant_doctor_server.py -q`
Expected: FAIL (`ImportError: cannot import name 'start_run'`).

- [ ] **Step 3: Implement the helpers in `sopilot/runner.py`**

Add these imports if missing: `from core.state_runtime.state import State` (already present) and `from core.human_review.review import ReviewRequest, ReviewDecision` (present). Add a planner-builder and the two helpers:

```python
def _build_planner(config: AgentConfig, media: Optional[Dict[str, Any]]):
    """Compile the SOP and assemble a Planner (shared by start_run/resume_run)."""
    sop_text = config.resolve(config.sop).read_text()
    output_schema = _resolve_output_schema(config)
    workflow = compile_sop(
        sop_text,
        sop_version=config.sop_version,
        output_schema=output_schema,
        compiler_config=config.model.compiler.model_dump(),
    )
    planner = Planner(
        workflow=workflow,
        adapters=_build_adapters(config),
        tool_router=_build_tool_router(config),
        run_inputs={"agent": config.name, "media": media or {}},
    )
    return planner


def start_run(
    agent_dir: str | Path,
    *,
    media: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run until the first HITL interrupt; return the drafted output + thread id.

    Uses a SQLite checkpointer file so a later :func:`resume_run` (a separate
    request/process) can resume the exact paused run.
    """
    config = load_agent_config(agent_dir)
    planner = _build_planner(config, media)
    if db_path is None:
        db_dir = config.agent_dir / ".sopilot"
        db_dir.mkdir(exist_ok=True)
        db_path = str(db_dir / "checkpoints.sqlite")

    thread_id = uuid.uuid4().hex
    run_config = {"configurable": {"thread_id": thread_id}}
    with build_checkpointer("sqlite", db_path) as cp:
        graph = compile_graph(planner, cp)
        result = graph.invoke(planner.initial_state(), run_config)
        interrupts = _interrupts(result)
        if interrupts:
            request = ReviewRequest.model_validate(_interrupt_value(interrupts[0]))
            return {
                "status": "interrupted",
                "thread_id": thread_id,
                "db_path": db_path,
                "review_request": request.model_dump(),
                "drafted_output": request.drafted_output,
                "evidence": list(graph.get_state(run_config).values.get("evidence", [])),
            }
        values = graph.get_state(run_config).values
        state = State.model_validate(values)
        return {
            "status": state.status,
            "thread_id": thread_id,
            "db_path": db_path,
            "final_output": state.final_output,
            "evidence": list(state.evidence),
        }


def resume_run(
    agent_dir: str | Path,
    *,
    thread_id: str,
    decision: Dict[str, Any],
    db_path: str,
    media: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resume a paused run with a human decision and finalize."""
    config = load_agent_config(agent_dir)
    planner = _build_planner(config, media)
    run_config = {"configurable": {"thread_id": thread_id}}
    review = ReviewDecision.model_validate(decision)
    with build_checkpointer("sqlite", db_path) as cp:
        graph = compile_graph(planner, cp)
        result = graph.invoke(Command(resume=review.model_dump()), run_config)
        # If another interrupt fires, auto-approve to completion (single-gate SOP).
        while _interrupts(result):
            result = graph.invoke(
                Command(resume=ReviewDecision().model_dump()), run_config
            )
        values = graph.get_state(run_config).values
    state = State.model_validate(values)
    out_path = config.agent_dir / "sample_outputs" / "latest_run.json"
    if state.final_output is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(state.final_output, indent=2))
    return {
        "status": state.status,
        "final_output": state.final_output,
        "evidence": list(state.evidence),
        "review": review.model_dump(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plant_doctor_server.py -q`
Expected: PASS (3 passed). These run on stub adapters (no keys) — fully offline.

- [ ] **Step 5: Commit**

```bash
git add sopilot/runner.py tests/test_plant_doctor_server.py
git commit -m "feat: two-phase start_run/resume_run for UI-driven HITL"
```

---

## Task 7: FastAPI server (start / decision / tts / static)

**Files:**
- Create: `app/__init__.py`
- Create: `app/server.py`
- Modify: `pyproject.toml` (add `[app]` extra + register `app` package)
- Test: `tests/test_plant_doctor_server.py` (add API tests using FastAPI TestClient)

- [ ] **Step 1: Add the optional dependency + package registration**

In `pyproject.toml`, under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]
app = ["fastapi>=0.115", "uvicorn>=0.30", "python-multipart>=0.0.9"]
```

And add `"app"` to `[tool.setuptools].packages`.

Then install: `pip install -e ".[app]"`
Expected: installs fastapi, uvicorn, python-multipart.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_plant_doctor_server.py`:

```python
import base64
import io

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _client():
    from app.server import create_app
    return TestClient(create_app())


def test_health_ok():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_run_then_decision_completes():
    client = _client()
    # Minimal multipart: two tiny images + one tiny audio file.
    files = [
        ("whole_plant_photo", ("whole.jpg", io.BytesIO(b"img1"), "image/jpeg")),
        ("closeup_photo", ("close.jpg", io.BytesIO(b"img2"), "image/jpeg")),
        ("care_habits_audio", ("a.wav", io.BytesIO(b"aud"), "audio/wav")),
    ]
    run = client.post("/api/run", files=files)
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "interrupted"
    thread_id = body["thread_id"]

    dec = client.post("/api/decision", json={
        "thread_id": thread_id, "db_path": body["db_path"],
        "decision": "approve", "reviewer": "ui",
    })
    assert dec.status_code == 200
    assert dec.json()["status"] == "completed"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_plant_doctor_server.py -k "health or run_then_decision" -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.server'`).

- [ ] **Step 4: Implement the server**

```python
# app/__init__.py
```
(empty file)

```python
# app/server.py
"""FastAPI server for the Plant Doctor demo (collect-then-run + real HITL).

Endpoints:
- POST /api/run       multipart images + audio -> run until the review interrupt
- POST /api/decision  approve/edit/reject -> resume + finalize
- POST /api/tts       synthesize care-plan speech, return an audio URL
- GET  /api/health    liveness
- GET  /              static frontend (app/web)
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sopilot.runner import resume_run, start_run

REPO = Path(__file__).resolve().parents[1]
AGENT = REPO / "examples" / "plant_doctor_agent"
WEB = Path(__file__).resolve().parent / "web"

# Map upload field names -> SOP step ids (compiler slugs) + evidence ids.
_VISION_STEPS = {
    "whole_plant_photo": "capture_the_whole_plant_in_frame",
    "closeup_photo": "capture_a_close_up_of_the_affected_leaves_or_stems",
}
_VOICE_STEP = "ask_the_gardener_about_light_watering_and_where_the_plant_lives"


def create_app() -> FastAPI:
    app = FastAPI(title="SOPilot Plant Doctor")

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True}

    @app.post("/api/run")
    async def run(
        whole_plant_photo: Optional[UploadFile] = File(default=None),
        closeup_photo: Optional[UploadFile] = File(default=None),
        care_habits_audio: Optional[UploadFile] = File(default=None),
    ) -> JSONResponse:
        media: Dict[str, Any] = {}
        for field, step_id in _VISION_STEPS.items():
            upload = {"whole_plant_photo": whole_plant_photo,
                      "closeup_photo": closeup_photo}[field]
            if upload is not None:
                raw = await upload.read()
                media[step_id] = {
                    "image_b64": base64.b64encode(raw).decode(),
                    "image_id": field,
                    "mime": upload.content_type or "image/jpeg",
                }
        if care_habits_audio is not None:
            raw = await care_habits_audio.read()
            tmp = Path(tempfile.gettempdir()) / f"plant_doctor_{care_habits_audio.filename}"
            tmp.write_bytes(raw)
            media[_VOICE_STEP] = {
                "audio_path": str(tmp),
                "recording_id": "care_habits_audio",
            }
        started = start_run(AGENT, media=media)
        return JSONResponse(started)

    @app.post("/api/decision")
    async def decision(payload: Dict[str, Any]) -> JSONResponse:
        final = resume_run(
            AGENT,
            thread_id=payload["thread_id"],
            decision={
                "decision": payload.get("decision", "approve"),
                "edits": payload.get("edits", {}),
                "note": payload.get("note", ""),
                "reviewer": payload.get("reviewer", "ui"),
            },
            db_path=payload["db_path"],
        )
        return JSONResponse(final)

    @app.post("/api/tts")
    async def tts(payload: Dict[str, Any]) -> JSONResponse:
        from core.voice_adapter import ElevenLabsVoiceAdapter
        from core.adapters.base import ActionRequest

        adapter = ElevenLabsVoiceAdapter()
        result = adapter.act(ActionRequest(
            step_id="care_plan", action="speak",
            payload={"text": payload.get("text", "")},
        ))
        return JSONResponse({"ok": result.ok, "audio_uri": result.data.get("audio_uri")})

    if WEB.exists():
        app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
    return app


app = create_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_plant_doctor_server.py -q`
Expected: PASS (all). The API tests run on stub adapters (no keys), so they are deterministic and offline.

- [ ] **Step 6: Commit**

```bash
git add app/__init__.py app/server.py pyproject.toml tests/test_plant_doctor_server.py
git commit -m "feat: FastAPI server for plant doctor (run/decision/tts)"
```

---

## Task 8: Frontend — camera + smart capture gating

**Files:**
- Create: `app/web/index.html`
- Create: `app/web/styles.css`
- Create: `app/web/app.js`

This task is browser-tested manually (camera/TF.js can't run in pytest). Each step still has an explicit verification.

- [ ] **Step 1: Create `app/web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SOPilot · Plant Doctor</title>
  <link rel="stylesheet" href="/styles.css" />
  <script src="https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.20.0/dist/tf.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@tensorflow-models/coco-ssd@2.2.3/dist/coco-ssd.min.js"></script>
</head>
<body>
  <header><h1>🪴 Plant Doctor</h1><p id="status">Loading detector…</p></header>
  <main>
    <section id="capture">
      <video id="cam" autoplay playsinline muted></video>
      <canvas id="work" hidden></canvas>
      <div id="prompt" class="prompt">① Show me the <b>whole plant</b></div>
      <div id="meter">stability <span id="stab">0</span> · sharpness <span id="sharp">0</span> · plant <span id="plant">no</span></div>
      <div id="thumbs"></div>
      <button id="recordBtn" disabled>🎤 Answer the question</button>
    </section>
    <section id="result" hidden>
      <h2>Care report</h2>
      <pre id="report"></pre>
      <audio id="careAudio" controls hidden></audio>
      <div class="actions">
        <button id="approve">Approve</button>
        <button id="reject">Reject</button>
      </div>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
```

Verify: `pip install -e ".[app]"` then `uvicorn app.server:app --reload` and open `http://127.0.0.1:8000` — the page renders and shows "Loading detector…".

- [ ] **Step 2: Create `app/web/styles.css`**

```css
:root { --bg:#f4f7f3; --card:#fff; --accent:#3f8f4f; --radius:18px; }
* { box-sizing:border-box; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
body { margin:0; background:var(--bg); color:#1f2a22; }
header { padding:18px 22px; }
header h1 { margin:0; font-size:22px; }
header p { margin:4px 0 0; color:#5a6b5e; }
main { display:grid; gap:18px; padding:0 22px 32px; max-width:760px; margin:0 auto; }
section { background:var(--card); border-radius:var(--radius); padding:18px; box-shadow:0 6px 24px rgba(40,70,45,.08); }
video { width:100%; border-radius:14px; background:#000; aspect-ratio:3/4; object-fit:cover; }
.prompt { margin:12px 0; font-size:18px; }
#meter { font-size:12px; color:#6b7a6e; margin-bottom:10px; }
#thumbs { display:flex; gap:8px; }
#thumbs img { width:72px; height:72px; object-fit:cover; border-radius:10px; border:2px solid var(--accent); }
button { background:var(--accent); color:#fff; border:0; padding:12px 18px; border-radius:12px; font-size:15px; cursor:pointer; }
button:disabled { opacity:.5; cursor:not-allowed; }
.actions { display:flex; gap:10px; margin-top:12px; }
#reject { background:#b4502f; }
pre { white-space:pre-wrap; background:#f0f4ef; padding:12px; border-radius:12px; font-size:13px; }
```

Verify: reload the page — styles applied, video area visible (browser will prompt for camera permission once `app.js` runs).

- [ ] **Step 3: Create `app/web/app.js` (camera + gating + capture)**

```javascript
// app/web/app.js
const SHOTS = [
  { field: "whole_plant_photo", prompt: "① Show me the <b>whole plant</b>" },
  { field: "closeup_photo", prompt: "② Show me the <b>affected leaves</b> (close-up)" },
];
const PLANT_CLASSES = new Set(["potted plant", "plant", "vase"]);
const STAB_THRESHOLD = 12;   // mean abs frame diff below this = steady
const SHARP_THRESHOLD = 8;   // edge energy above this = sharp
const HOLD_FRAMES = 8;       // consecutive good frames before capture

const els = {
  cam: document.getElementById("cam"), work: document.getElementById("work"),
  prompt: document.getElementById("prompt"), status: document.getElementById("status"),
  stab: document.getElementById("stab"), sharp: document.getElementById("sharp"),
  plant: document.getElementById("plant"), thumbs: document.getElementById("thumbs"),
  recordBtn: document.getElementById("recordBtn"),
};
const captured = {};   // field -> Blob
let model = null, prevGray = null, shotIdx = 0, goodStreak = 0;

async function init() {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  els.cam.srcObject = stream;
  await els.cam.play();
  model = await cocoSsd.load();
  els.status.textContent = "Point the camera at your plant.";
  els.prompt.innerHTML = SHOTS[0].prompt;
  requestAnimationFrame(loop);
}

function grayscale(ctx, w, h) {
  const { data } = ctx.getImageData(0, 0, w, h);
  const g = new Float32Array(w * h);
  for (let i = 0; i < g.length; i++) g[i] = 0.299*data[i*4] + 0.587*data[i*4+1] + 0.114*data[i*4+2];
  return g;
}
function meanAbsDiff(a, b) { let s = 0; for (let i=0;i<a.length;i++) s += Math.abs(a[i]-b[i]); return s/a.length; }
function edgeEnergy(g, w, h) {
  let s = 0, n = 0;
  for (let y=1;y<h-1;y+=2) for (let x=1;x<w-1;x+=2) {
    const gx = g[y*w+x+1]-g[y*w+x-1], gy = g[(y+1)*w+x]-g[(y-1)*w+x];
    s += Math.abs(gx)+Math.abs(gy); n++;
  }
  return n ? s/n : 0;
}

async function loop() {
  if (shotIdx >= SHOTS.length) return;
  const w = 240, h = 320;
  const ctx = els.work.getContext("2d");
  els.work.width = w; els.work.height = h;
  ctx.drawImage(els.cam, 0, 0, w, h);
  const gray = grayscale(ctx, w, h);
  const stab = prevGray ? meanAbsDiff(gray, prevGray) : 999;
  const sharp = edgeEnergy(gray, w, h);
  prevGray = gray;

  const preds = await model.detect(els.cam);
  const hasPlant = preds.some(p => PLANT_CLASSES.has(p.class) && p.score > 0.45);

  els.stab.textContent = stab.toFixed(0);
  els.sharp.textContent = sharp.toFixed(0);
  els.plant.textContent = hasPlant ? "yes" : "no";

  const good = hasPlant && stab < STAB_THRESHOLD && sharp > SHARP_THRESHOLD;
  goodStreak = good ? goodStreak + 1 : 0;
  if (goodStreak >= HOLD_FRAMES) { await capture(); goodStreak = 0; }
  requestAnimationFrame(loop);
}

async function capture() {
  const shot = SHOTS[shotIdx];
  const full = document.createElement("canvas");
  full.width = els.cam.videoWidth; full.height = els.cam.videoHeight;
  full.getContext("2d").drawImage(els.cam, 0, 0);
  const blob = await new Promise(r => full.toBlob(r, "image/jpeg", 0.85));
  captured[shot.field] = blob;
  const img = document.createElement("img");
  img.src = URL.createObjectURL(blob);
  els.thumbs.appendChild(img);
  shotIdx++;
  if (shotIdx < SHOTS.length) {
    els.prompt.innerHTML = SHOTS[shotIdx].prompt;
  } else {
    els.prompt.innerHTML = "✅ Photos captured.";
    els.status.textContent = "Now tap the mic and answer.";
    els.recordBtn.disabled = false;
  }
}

window.captured = captured; // shared with the recording/run module
init().catch(e => { els.status.textContent = "Camera/model error: " + e.message; });
```

Verify in browser: point at a plant (or a plant photo on another screen). The `plant` meter flips to `yes`; holding steady captures shot ①, then the prompt advances to ②; a second steady capture enables the mic button. Two thumbnails appear.

- [ ] **Step 4: Commit**

```bash
git add app/web/index.html app/web/styles.css app/web/app.js
git commit -m "feat: plant doctor web UI with smart camera capture (TF.js + heuristics)"
```

---

## Task 9: Frontend — record answer, run, review, speak care plan

**Files:**
- Modify: `app/web/app.js` (append recording + run/review wiring)

Browser-tested manually.

- [ ] **Step 1: Append recording + run + review logic to `app/web/app.js`**

```javascript
// --- voice recording + run + HITL review ---
let mediaRecorder = null, audioChunks = [], runState = null;

els.recordBtn.addEventListener("click", async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") { mediaRecorder.stop(); return; }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
  mediaRecorder.onstop = async () => {
    const audio = new Blob(audioChunks, { type: "audio/webm" });
    els.recordBtn.textContent = "⏳ Diagnosing…";
    els.recordBtn.disabled = true;
    await runAgent(audio);
  };
  mediaRecorder.start();
  els.recordBtn.textContent = "⏹ Stop & submit";
});

async function runAgent(audioBlob) {
  const fd = new FormData();
  if (window.captured.whole_plant_photo) fd.append("whole_plant_photo", window.captured.whole_plant_photo, "whole.jpg");
  if (window.captured.closeup_photo) fd.append("closeup_photo", window.captured.closeup_photo, "close.jpg");
  fd.append("care_habits_audio", audioBlob, "answer.webm");
  const resp = await fetch("/api/run", { method: "POST", body: fd });
  runState = await resp.json();
  showReport(runState.drafted_output || runState.final_output, "Drafted — please review");
}

function showReport(output, title) {
  document.getElementById("result").hidden = false;
  document.querySelector("#result h2").textContent = title;
  document.getElementById("report").textContent = JSON.stringify(output, null, 2);
  speakCarePlan(output);
}

async function speakCarePlan(output) {
  const plan = output && output.care_plan ? output.care_plan : output && output.summary;
  const text = typeof plan === "string" ? plan : (plan && plan.value) || (output && output.summary) || "";
  if (!text) return;
  try {
    const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: typeof text === "string" ? text : JSON.stringify(text) }) });
    const j = await r.json();
    if (j.audio_uri && /^https?:|^\//.test(j.audio_uri)) {
      const a = document.getElementById("careAudio"); a.src = j.audio_uri; a.hidden = false;
    }
  } catch (_) { /* TTS optional */ }
}

document.getElementById("approve").addEventListener("click", () => decide("approve"));
document.getElementById("reject").addEventListener("click", () => decide("reject"));

async function decide(decision) {
  const r = await fetch("/api/decision", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: runState.thread_id, db_path: runState.db_path, decision, reviewer: "ui" }) });
  const final = await r.json();
  showReport(final.final_output, decision === "approve" ? "✅ Approved report" : "🚫 Rejected");
}
```

Verify in browser (full loop): with `OPENAI_API_KEY` + `ELEVENLABS_API_KEY` exported before launching the server, run the capture → record → diagnose flow; a drafted report appears (with real `gpt-4o`/`elevenlabs` content), Approve produces the finalized report. Without keys, it still completes using stub adapters.

- [ ] **Step 2: Commit**

```bash
git add app/web/app.js
git commit -m "feat: plant doctor UI run/review/speak care-plan flow"
```

---

## Task 10: Docs + full regression

**Files:**
- Modify: `README.md`
- Test: full suite

- [ ] **Step 1: Add a Plant Doctor section to `README.md`**

Add under the Quickstart list:

```markdown
# Live voice + vision plant doctor (web UI; real models optional):
pip install -e ".[app]"
export OPENAI_API_KEY=...        # optional: real GPT-4o vision
export ELEVENLABS_API_KEY=...    # optional: real ElevenLabs STT/TTS
uvicorn app.server:app --reload  # open http://127.0.0.1:8000
# Headless (stub, no keys):
python -m sopilot run examples/plant_doctor_agent
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS (all existing + new tests green).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the plant doctor demo + web UI"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- SOP + schema + config → Task 1. Real adapters → Tasks 4–5. Provider selection + media threading → Tasks 2–3. Collect-then-run + real interrupt/resume HITL → Tasks 6–7. Web UI (camera, TF.js gating, voice, review, TTS) → Tasks 8–9. Failure cases (no image/audio → low confidence; no keys → stub fallback) → Tasks 2,4,5. Cost/latency (2 VLM calls, 1 STT, 1 TTS) → enforced by the 2-shot UI + single voice step. "Explicitly unchanged" core files → Conventions + Task notes.
- Success criteria #1–#5 from the spec map to Task 1 (compile shape, stub run), Tasks 4–5 + registry (real models via `model` fields), Tasks 8–9 (UI loop), and the "do NOT edit" Conventions (#5).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output.

**Type consistency:** `media[step_id]` shape is consistent across server (`image_b64`/`image_id`/`mime`, `audio_path`/`recording_id`/`options`), `OpenAIVisionAdapter.observe`, and `ElevenLabsVoiceAdapter.observe`. `start_run`/`resume_run` return dicts with consistent keys (`status`, `thread_id`, `db_path`, `review_request`/`drafted_output`/`final_output`, `evidence`) consumed identically by the server and tests. Adapter classes (`OpenAIVisionAdapter`, `ElevenLabsVoiceAdapter`) match their imports/exports.

**Known ordering note:** Task 2's registry imports the real adapters from Tasks 4–5. Implement Tasks 4 and 5 before running Task 2's Step 5 (called out inline in Task 2 Step 4).
