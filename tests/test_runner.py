"""End-to-end tests: full graph run, HITL interrupt/resume, and reject flow."""

from pathlib import Path

from langgraph.types import Command

from core.human_review.review import AutoApprovePolicy, ReviewRequest
from core.planner.planner import Planner
from core.sop_compiler import compile_sop
from core.state_runtime.graph import build_checkpointer, compile_graph
from core.state_runtime.state import State
from core.tool_router import StubMCPConnector, ToolRouter
from core.vision_adapter import VisionStubAdapter
from sopilot.runner import run_agent

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

MINI_SOP = """# Mini

## Do
- Take a photo of the item [vision] [produces: item]
- Send the resolution to the customer [review: customer_response] [produces: reply]
"""


def _run(policy: AutoApprovePolicy):
    wf = compile_sop(MINI_SOP)
    planner = Planner(
        wf,
        adapters={"vision": VisionStubAdapter(cues={})},
        tool_router=ToolRouter([StubMCPConnector("noop")]),
    )
    events = []
    with build_checkpointer("memory") as cp:
        graph = compile_graph(planner, cp)
        cfg = {"configurable": {"thread_id": "test"}}
        result = graph.invoke(planner.initial_state(), cfg)
        while isinstance(result, dict) and result.get("__interrupt__"):
            intr = result["__interrupt__"][0]
            req = ReviewRequest.model_validate(intr.value)
            events.append(req.trigger)
            decision = policy.decide(req)
            result = graph.invoke(Command(resume=decision.model_dump()), cfg)
        values = graph.get_state(cfg).values
    return State.model_validate(values), events


def test_hitl_interrupt_is_hit_and_resumed():
    state, events = _run(AutoApprovePolicy())
    assert events == ["customer_response"]  # the interrupt fired exactly once
    assert state.status == "completed"
    assert len(state.evidence) >= 2
    assert any(o["decision"] == "approve" for o in state.human_overrides)
    assert state.final_output is not None


def test_reject_halts_run():
    policy = AutoApprovePolicy(reject_triggers=["customer_response"])
    state, events = _run(policy)
    assert events == ["customer_response"]
    assert state.status == "rejected"
    assert any(o["decision"] == "reject" for o in state.human_overrides)


def test_support_runbook_example_completes():
    result = run_agent(
        EXAMPLES / "support_runbook_agent", checkpointer_backend="memory"
    )
    assert result.state.status == "completed"
    assert result.review_events  # a HITL checkpoint was hit
    assert len(result.state.evidence) > 0
    # Branching dropped the not-taken branch (incident_active=True).
    assert "prepare_standard_fix" not in result.state.completed_steps
    assert "prepare_incident_reply" in result.state.completed_steps
