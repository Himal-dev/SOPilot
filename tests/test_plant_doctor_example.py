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
    summaries = [obs["summary"] for obs in result.state.observations]
    assert any("green veins" in summary for summary in summaries)
    assert any("low indoor light" in summary for summary in summaries)
    assert result.state.final_output is not None
    assert "care_report" in result.state.final_output
