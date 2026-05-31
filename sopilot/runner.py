"""Assemble and run an SOP agent end-to-end.

Pipeline: load config -> compile SOP -> build adapters + tool router -> compile
the LangGraph with a checkpointer -> run, handling HITL interrupts (auto-approve
in non-interactive mode) -> write structured output -> return the final state.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.types import Command

from core.human_review.review import AutoApprovePolicy, ReviewDecision, ReviewRequest
from core.planner.planner import Planner
from core.sop_compiler import compile_sop
from core.sop_compiler.workflow import CompiledWorkflow
from core.state_runtime.graph import build_checkpointer, compile_graph
from core.state_runtime.state import State
from core.tool_router import StubMCPConnector, ToolRouter
from core.vision_adapter import OpenAIVisionAdapter, VisionStubAdapter
from core.voice_adapter import ElevenLabsVoiceAdapter, VoiceStubAdapter
from sopilot.config import AgentConfig, load_agent_config, load_json
from sopilot.scaffold import (
    adapter_status,
    assert_live_provider_status,
    has_agent_transcript,
)

_STUB_FACTORIES = {
    "vision": VisionStubAdapter,
    "voice": VoiceStubAdapter,
}


@dataclass
class RunResult:
    workflow: CompiledWorkflow
    state: State
    output_path: Optional[Path]
    review_events: List[Dict[str, Any]] = field(default_factory=list)


def _load_cues(config: AgentConfig, adapter_cfg) -> Dict[str, Any]:
    if not adapter_cfg.cues:
        return {}
    path = config.resolve(adapter_cfg.cues)
    if not path.exists():
        return {}
    return load_json(path)


def _build_adapter(
    modality: str,
    adapter_cfg,
    config: AgentConfig,
    media: Optional[Dict[str, Any]] = None,
):
    """Pick a real adapter when its provider and API key are available.

    Provider configuration is intentionally fail-open to the deterministic
    stubs so local demos and tests keep working without secrets.
    """
    cues = _load_cues(config, adapter_cfg)
    provider = (getattr(adapter_cfg, "provider", "stub") or "stub").lower()
    status = adapter_status(modality, adapter_cfg, config, media=media)
    assert_live_provider_status(status)

    if (
        modality == "vision"
        and provider == "openai"
        and status.live_ready
    ):
        return OpenAIVisionAdapter(name="vision")
    if (
        modality == "voice"
        and provider == "elevenlabs"
        and (status.live_ready or has_agent_transcript(media))
    ):
        return ElevenLabsVoiceAdapter(name="voice")

    stub = _STUB_FACTORIES.get(modality)
    return stub(cues=cues) if stub else None


def _build_adapters(
    config: AgentConfig, media: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    adapters: Dict[str, Any] = {}
    for modality, adapter_cfg in config.adapters.items():
        if not adapter_cfg.enabled:
            continue
        adapter = _build_adapter(modality, adapter_cfg, config, media)
        if adapter is not None:
            adapters[modality] = adapter
    return adapters


def _build_tool_router(config: AgentConfig) -> ToolRouter:
    router = ToolRouter()
    for server in config.mcp_servers:
        if server.type == "kids_voice_local":
            from core.kids_voice_assessment.tools import KidsVoiceLocalMCPConnector

            router.add_connector(KidsVoiceLocalMCPConnector())
            continue
        tools = list(server.tools)
        resources = list(server.resources)
        prompts = list(server.prompts)
        responses = dict(server.responses)
        if server.catalog:
            catalog_path = config.resolve(server.catalog)
            if catalog_path.exists():
                catalog = load_json(catalog_path)
                tools = catalog.get("tools", tools)
                resources = catalog.get("resources", resources)
                prompts = catalog.get("prompts", prompts)
                responses = catalog.get("responses", responses)
        router.add_connector(
            StubMCPConnector(
                name=server.name,
                tools=tools,
                resources=resources,
                prompts=prompts,
                responses=responses,
            )
        )
    return router


def _resolve_output_schema(config: AgentConfig) -> Optional[Dict[str, Any]]:
    """Return the output schema dict, or ``None`` to ask the compiler to suggest."""
    if config.output_schema.strip().lower() == "suggest":
        return None
    schema_path = config.resolve(config.output_schema)
    if not schema_path.exists():
        return None
    return load_json(schema_path)


def _compile_workflow(
    config: AgentConfig, output_schema: Optional[Dict[str, Any]]
) -> CompiledWorkflow:
    return compile_sop(
        config.resolve(config.sop).read_text(),
        sop_version=config.sop_version,
        output_schema=output_schema,
        compiler_config=config.model.compiler.model_dump(),
    )


def _build_planner(
    config: AgentConfig, media: Optional[Dict[str, Any]] = None
) -> Planner:
    """Compile the SOP and assemble a Planner for one run."""
    output_schema = _resolve_output_schema(config)
    workflow = _compile_workflow(config, output_schema)
    return Planner(
        workflow=workflow,
        adapters=_build_adapters(config, media),
        tool_router=_build_tool_router(config),
        run_inputs={"agent": config.name, "media": media or {}},
    )


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
    """Run a single agent and return the result.

    ``interactive=False`` (default) auto-approves HITL checkpoints via the
    configured :class:`AutoApprovePolicy`, so the run completes headlessly while
    still exercising the real interrupt/resume path.
    """
    config = load_agent_config(agent_dir)
    log = on_event or (lambda *_: None)

    output_schema = _resolve_output_schema(config)
    workflow = _compile_workflow(config, output_schema)
    log("compiled", {"steps": len(workflow.steps), "source": workflow.source})

    # If the schema was suggested, persist it so the author can edit it.
    if output_schema is None:
        suggested = config.resolve("suggested_output_schema.json")
        suggested.write_text(json.dumps(workflow.output_schema, indent=2))
        log("schema_suggested", {"path": str(suggested)})

    adapters = _build_adapters(config, media)
    tool_router = _build_tool_router(config)
    planner = Planner(
        workflow=workflow,
        adapters=adapters,
        tool_router=tool_router,
        run_inputs={"agent": config.name, "media": media or {}},
    )

    policy = AutoApprovePolicy(
        approve=config.hitl.auto_approve,
        reject_triggers=config.hitl.reject_triggers,
        reject_above_risk=config.hitl.reject_above_risk,
        reviewer=config.hitl.reviewer,
    )

    if db_path is None and checkpointer_backend == "sqlite":
        db_dir = config.agent_dir / ".sopilot"
        db_dir.mkdir(exist_ok=True)
        db_path = str(db_dir / "checkpoints.sqlite")

    review_events: List[Dict[str, Any]] = []
    thread_id = uuid.uuid4().hex
    run_config = {"configurable": {"thread_id": thread_id}}

    with build_checkpointer(checkpointer_backend, db_path or ":memory:") as cp:
        graph = compile_graph(planner, cp)
        result = graph.invoke(planner.initial_state(), run_config)

        while _interrupts(result):
            intr = _interrupts(result)[0]
            request = ReviewRequest.model_validate(_interrupt_value(intr))
            decision = _decide(request, policy, interactive)
            review_events.append(
                {
                    "review_point": request.review_point,
                    "trigger": request.trigger,
                    "step_id": request.step_id,
                    "risk": request.risk,
                    "decision": decision.decision,
                    "reviewer": decision.reviewer,
                }
            )
            log("hitl", review_events[-1])
            result = graph.invoke(
                Command(resume=decision.model_dump()), run_config
            )

        final_values = graph.get_state(run_config).values

    state = State.model_validate(final_values)

    out_path: Optional[Path] = None
    if state.final_output is not None:
        out_path = (
            Path(output_path)
            if output_path
            else config.agent_dir / "sample_outputs" / "latest_run.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(state.final_output, indent=2))
        log("output_written", {"path": str(out_path)})

    return RunResult(
        workflow=workflow,
        state=state,
        output_path=out_path,
        review_events=review_events,
    )


def start_run(
    agent_dir: str | Path,
    *,
    media: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
    auto_finalize: Optional[bool] = None,
    auto_finalize_reviewer: Optional[str] = None,
) -> Dict[str, Any]:
    """Run until the first HITL interrupt and return a resume handle."""
    config = load_agent_config(agent_dir)
    planner = _build_planner(config, media)
    if auto_finalize is None:
        auto_finalize = config.runtime.auto_finalize_on_start
    reviewer = auto_finalize_reviewer or config.runtime.auto_finalize_reviewer
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
        while interrupts and auto_finalize:
            decision = ReviewDecision(decision="approve", reviewer=reviewer)
            result = graph.invoke(Command(resume=decision.model_dump()), run_config)
            interrupts = _interrupts(result)
        values = graph.get_state(run_config).values
        state = State.model_validate(values)
        if interrupts:
            request = ReviewRequest.model_validate(_interrupt_value(interrupts[0]))
            return {
                "status": "interrupted",
                "thread_id": thread_id,
                "db_path": db_path,
                "review_request": request.model_dump(),
                "drafted_output": request.drafted_output,
                "evidence": list(state.evidence),
                "observations": list(state.observations),
                "risks": list(state.risks),
                "step_outputs": dict(state.step_outputs),
            }
        return {
            "status": state.status,
            "thread_id": thread_id,
            "db_path": db_path,
            "final_output": state.final_output,
            "evidence": list(state.evidence),
            "observations": list(state.observations),
            "risks": list(state.risks),
            "step_outputs": dict(state.step_outputs),
            "human_overrides": list(state.human_overrides),
        }


def resume_run(
    agent_dir: str | Path,
    *,
    thread_id: str,
    decision: Dict[str, Any],
    db_path: str,
    media: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resume a paused run with a human decision and return the final state."""
    config = load_agent_config(agent_dir)
    planner = _build_planner(config, media)
    run_config = {"configurable": {"thread_id": thread_id}}
    review = ReviewDecision.model_validate(decision)
    with build_checkpointer("sqlite", db_path) as cp:
        graph = compile_graph(planner, cp)
        result = graph.invoke(Command(resume=review.model_dump()), run_config)
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
        "observations": list(state.observations),
        "risks": list(state.risks),
        "step_outputs": dict(state.step_outputs),
        "human_overrides": list(state.human_overrides),
        "review": review.model_dump(),
    }


def _interrupts(result: Any) -> List[Any]:
    if isinstance(result, dict):
        return list(result.get("__interrupt__", []) or [])
    return []


def _interrupt_value(intr: Any) -> Dict[str, Any]:
    value = getattr(intr, "value", intr)
    return value if isinstance(value, dict) else {}


def _decide(
    request: ReviewRequest, policy: AutoApprovePolicy, interactive: bool
) -> ReviewDecision:
    if not interactive:
        return policy.decide(request)
    return _prompt_human(request)


def _prompt_human(request: ReviewRequest) -> ReviewDecision:
    """Minimal interactive prompt for a human reviewer."""
    print("\n=== HUMAN REVIEW REQUIRED ===")
    print(f"  point   : {request.review_point} ({request.trigger}, risk={request.risk})")
    print(f"  step    : {request.step_id}")
    print(f"  detail  : {request.description}")
    print(f"  drafted : {json.dumps(request.drafted_output, indent=2)}")
    print(f"  evidence: {request.evidence_refs}")
    choice = input("  [a]pprove / [e]dit / [r]eject? ").strip().lower()
    if choice.startswith("r"):
        note = input("  rejection note: ").strip()
        return ReviewDecision(decision="reject", reviewer="human", note=note)
    if choice.startswith("e"):
        raw = input("  edits as JSON ({}): ").strip() or "{}"
        try:
            edits = json.loads(raw)
        except json.JSONDecodeError:
            edits = {}
        return ReviewDecision(decision="edit", edits=edits, reviewer="human")
    return ReviewDecision(decision="approve", reviewer="human")
