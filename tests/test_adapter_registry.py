"""Provider-aware adapter selection with deterministic stub fallback."""

from pathlib import Path

from core.vision_adapter import VisionStubAdapter
from core.voice_adapter import VoiceStubAdapter
from sopilot.config import load_agent_config
from sopilot.runner import _build_adapters

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


def test_selects_voice_adapter_for_agent_transcript_without_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    config = load_agent_config(AGENT)
    adapters = _build_adapters(
        config,
        media={"ask": {"transcript": "I water weekly in bright indirect light"}},
    )
    assert adapters["voice"].__class__.__name__ == "ElevenLabsVoiceAdapter"


def test_media_is_threaded_into_run_inputs():
    from core.adapters.base import ActionResult, Observation
    from core.planner.planner import Planner
    from core.sop_compiler import compile_sop

    wf = compile_sop("# T\n## Do\n- Take a photo [vision] [produces: x]\n")
    captured = {}

    class RecordingAdapter:
        name = "vision"

        def capabilities(self):
            return ["observe"]

        def observe(self, request):
            captured["inputs"] = request.inputs
            return Observation(
                step_id=request.step_id, source="vision", confidence=0.9
            )

        def act(self, request):
            return ActionResult()

    planner = Planner(
        wf,
        adapters={"vision": RecordingAdapter()},
        run_inputs={"agent": "t", "media": {"take_a_photo": {"image_id": "p1"}}},
    )
    state = planner.initial_state()
    state.current_step = wf.steps[0].id
    planner.execute_node(state)
    assert "media" in captured["inputs"]
    assert captured["inputs"]["media"]["take_a_photo"]["image_id"] == "p1"
