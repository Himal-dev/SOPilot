"""The planner: turns a CompiledWorkflow + adapters + tools into graph nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langgraph.types import interrupt

from core.adapters.base import Adapter, ObserveRequest
from core.evidence_ledger import EvidenceLedger
from core.human_review.review import ReviewDecision, ReviewRequest, apply_decision
from core.planner.expr import safe_eval
from core.sop_compiler.workflow import CompiledWorkflow, WorkflowStep
from core.state_runtime.state import (
    HumanOverride,
    Observation,
    Risk,
    State,
    ToolResult,
)
from core.tool_router import ToolRouter

# Node names (also the keys used when wiring the graph).
PLAN = "plan"
EXECUTE = "execute"
REVIEW = "review"
FINALIZE = "finalize"


class Planner:
    """Executes a compiled SOP. Stateless w.r.t. runs; the graph carries state."""

    def __init__(
        self,
        workflow: CompiledWorkflow,
        adapters: Optional[Dict[str, Adapter]] = None,
        tool_router: Optional[ToolRouter] = None,
        run_inputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.workflow = workflow
        self.adapters = adapters or {}
        self.tool_router = tool_router or ToolRouter()
        self.run_inputs = run_inputs or {}

    # -- initial state ---------------------------------------------------------

    def initial_state(self) -> State:
        """Seed a fresh run state from the compiled workflow."""
        return State(
            goal=self.workflow.goal,
            sop_version=self.workflow.sop_version,
            pending_steps=[s.id for s in self.workflow.steps],
            current_step=None,
            status="running",
        )

    # -- nodes -----------------------------------------------------------------

    def plan_node(self, state: State) -> Dict[str, Any]:
        """Pick the next step to run (or none, ending the loop)."""
        if state.status != "running" or not state.pending_steps:
            return {"current_step": None}
        nxt = state.pending_steps[0]
        return {"current_step": nxt, "log": [f"plan -> {nxt}"]}

    def execute_node(self, state: State) -> Dict[str, Any]:
        """Run the current step: sense/act, validate, record evidence, branch."""
        step = self.workflow.step(state.current_step or "")
        if step is None:
            return {}

        ledger = EvidenceLedger()
        observations: List[Dict[str, Any]] = []
        tool_results: List[Dict[str, Any]] = []
        risks: List[Dict[str, Any]] = []
        log: List[str] = []

        ctx: Dict[str, Any] = {}
        confidence = 0.7
        produced: Dict[str, Any] = {}

        if step.modality in ("vision", "voice"):
            confidence, produced, ctx = self._run_perception(
                step, ledger, observations, risks, log
            )
        elif step.modality == "tool":
            confidence, produced, ctx = self._run_tools(
                step, ledger, tool_results, observations, risks, log
            )
        else:  # reason / none
            confidence, produced, ctx = self._run_reason(
                step, ledger, observations, log
            )

        ctx["confidence"] = confidence

        # Validation rules.
        for rule in self.workflow.rules_for(step.id):
            ok = bool(safe_eval(rule.expression, ctx))
            if not ok:
                risks.append(
                    Risk(
                        step_id=step.id,
                        kind="validation_failed",
                        severity=rule.severity,
                        detail=rule.message or rule.expression,
                    ).model_dump()
                )
                log.append(f"validation failed [{rule.id}] on {step.id}")

        # Confidence-based next-action: low confidence -> flag for recapture.
        if confidence < step.min_confidence:
            risks.append(
                Risk(
                    step_id=step.id,
                    kind="low_confidence",
                    severity="warning",
                    detail=f"confidence {confidence:.2f} < min "
                    f"{step.min_confidence:.2f}; recommend recapture/review.",
                ).model_dump()
            )

        # Decision points: take the chosen branch next and drop the other.
        pending_remaining = [s for s in state.pending_steps if s != step.id]
        for dp in self.workflow.decisions_for(step.id):
            branch = bool(safe_eval(dp.condition, ctx))
            chosen = dp.on_true if branch else dp.on_false
            dropped = dp.on_false if branch else dp.on_true
            log.append(f"decision {dp.id}: {dp.condition} -> {branch} -> {chosen}")
            if dropped and dropped in pending_remaining:
                pending_remaining.remove(dropped)
            if chosen and chosen in pending_remaining:
                pending_remaining.remove(chosen)
                pending_remaining.insert(0, chosen)

        merged_outputs = {**state.step_outputs, **produced}

        return {
            "completed_steps": [step.id],
            "pending_steps": pending_remaining,
            "observations": observations,
            "evidence": ledger.to_list(),
            "tool_results": tool_results,
            "risks": risks,
            "step_outputs": merged_outputs,
            "log": log,
        }

    def review_node(self, state: State) -> Dict[str, Any]:
        """Human-in-the-loop gate. Pauses via ``interrupt`` and resumes."""
        step = self.workflow.step(state.current_step or "")
        assert step is not None and step.human_review_point is not None
        rp = self.workflow.review_point(step.human_review_point)
        assert rp is not None

        drafted = {f: state.step_outputs.get(f) for f in step.produces}
        evidence_refs = [
            e["id"] for e in state.evidence if e.get("step_id") == step.id
        ]
        request = ReviewRequest(
            review_point=rp.id,
            trigger=rp.trigger,
            step_id=step.id,
            risk=rp.risk,
            description=rp.description,
            drafted_output=drafted,
            evidence_refs=evidence_refs,
            open_risks=list(state.risks),
        )

        # This is the real LangGraph pause point. The runner resumes with a
        # ReviewDecision (interactive prompt or AutoApprovePolicy).
        resumed = interrupt(request.model_dump())

        decision = (
            ReviewDecision.model_validate(resumed)
            if resumed
            else ReviewDecision()
        )
        merged_outputs = apply_decision(decision, state.step_outputs)
        override = HumanOverride(
            step_id=step.id,
            review_point=rp.id,
            decision=decision.decision,
            edits=decision.edits,
            note=decision.note,
            reviewer=decision.reviewer,
        ).model_dump()

        updates: Dict[str, Any] = {
            "human_overrides": [override],
            "step_outputs": merged_outputs,
            "log": [f"review {rp.id}: {decision.decision} by {decision.reviewer}"],
        }
        if decision.decision == "reject":
            updates["status"] = "rejected"
        return updates

    def finalize_node(self, state: State) -> Dict[str, Any]:
        """Generate the structured output from state + evidence."""
        # Imported here to keep import graph shallow / avoid cycles at module load.
        from core.output_generator import generate_output

        final_status = "rejected" if state.status == "rejected" else "completed"
        state.status = final_status
        output = generate_output(state, self.workflow.output_schema)
        return {
            "final_output": output,
            "status": final_status,
            "current_step": None,
            "log": [f"finalized: status={final_status}"],
        }

    # -- routers ---------------------------------------------------------------

    def route_after_plan(self, state: State) -> str:
        if state.status != "running" or not state.current_step:
            return FINALIZE
        return EXECUTE

    def route_after_execute(self, state: State) -> str:
        step = self.workflow.step(state.current_step or "")
        if step is not None and step.human_review_point:
            already = any(
                o.get("review_point") == step.human_review_point
                for o in state.human_overrides
            )
            if not already:
                return REVIEW
        return PLAN

    def route_after_review(self, state: State) -> str:
        return FINALIZE if state.status == "rejected" else PLAN

    # -- modality helpers ------------------------------------------------------

    def _run_perception(self, step, ledger, observations, risks, log):
        adapter = self.adapters.get(step.modality)
        if adapter is None:
            log.append(f"no '{step.modality}' adapter; skipping {step.id}")
            risks.append(
                Risk(
                    step_id=step.id,
                    kind="missing_adapter",
                    severity="error",
                    detail=f"no adapter for modality '{step.modality}'",
                ).model_dump()
            )
            return 0.0, {}, {}

        obs = adapter.observe(
            ObserveRequest(
                step_id=step.id,
                instruction=step.instruction,
                inputs={"goal": self.workflow.goal, **self.run_inputs},
            )
        )
        observations.append(Observation(**obs.model_dump()).model_dump())
        refs = obs.evidence_refs or step.required_evidence
        entry = ledger.record(
            claim=obs.summary or step.title,
            evidence=refs,
            model=obs.model,
            confidence=obs.confidence,
            step_id=step.id,
        )
        log.append(f"{step.modality} observed {step.id} ({obs.confidence:.2f})")
        produced = {
            field: {
                "value": obs.summary,
                "confidence": obs.confidence,
                "content": obs.content,
                "evidence": [entry.id],
            }
            for field in step.produces
        }
        ctx = {**obs.content, "confidence": obs.confidence}
        return obs.confidence, produced, ctx

    def _run_tools(self, step, ledger, tool_results, observations, risks, log):
        all_ok = True
        merged_result: Dict[str, Any] = {}
        evidence_ids: List[str] = []
        requirements = step.tools_needed or [step.id]
        for requirement in requirements:
            spec = self.tool_router.select_tool(requirement)
            if spec is None:
                all_ok = False
                risks.append(
                    Risk(
                        step_id=step.id,
                        kind="tool_unavailable",
                        severity="error",
                        detail=f"no tool for requirement '{requirement}'",
                    ).model_dump()
                )
                log.append(f"tool unavailable for '{requirement}' on {step.id}")
                continue
            call = self.tool_router.call(spec.name, {"step": step.id})
            tool_results.append(
                ToolResult(
                    step_id=step.id,
                    server=call.server,
                    tool=call.tool,
                    ok=call.ok,
                    arguments={"step": step.id},
                    result=call.result,
                    error=call.error,
                ).model_dump()
            )
            all_ok = all_ok and call.ok
            merged_result[spec.name] = call.result
            entry = ledger.record(
                claim=f"{step.title}: called {spec.name}",
                evidence=[f"tool:{call.server}:{spec.name}"],
                model=f"mcp:{call.server}",
                confidence=0.9 if call.ok else 0.0,
                step_id=step.id,
            )
            evidence_ids.append(entry.id)
            log.append(f"tool {spec.name} ok={call.ok} on {step.id}")

        confidence = 0.9 if all_ok and requirements else 0.2
        observations.append(
            Observation(
                step_id=step.id,
                source="tool",
                summary=f"{step.title}: {len(tool_results)} tool call(s)",
                content=merged_result,
                confidence=confidence,
                model="tool-router",
            ).model_dump()
        )
        produced = {
            field: {
                "value": merged_result,
                "confidence": confidence,
                "evidence": evidence_ids,
            }
            for field in step.produces
        }
        ctx = {"ok": all_ok, "confidence": confidence, **_flatten(merged_result)}
        return confidence, produced, ctx

    def _run_reason(self, step, ledger, observations, log):
        summary = step.summary_template or step.instruction or step.title
        confidence = 0.75
        entry = ledger.record(
            claim=summary,
            evidence=[],
            model="planner-reason",
            confidence=confidence,
            step_id=step.id,
        )
        observations.append(
            Observation(
                step_id=step.id,
                source="reason",
                summary=summary,
                confidence=confidence,
                model="planner-reason",
            ).model_dump()
        )
        log.append(f"reasoned {step.id}")
        produced = {
            field: {
                "value": summary,
                "confidence": confidence,
                "evidence": [entry.id],
            }
            for field in step.produces
        }
        return confidence, produced, {"confidence": confidence}


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten one level of nested tool results for decision/validation context."""
    flat: Dict[str, Any] = {}
    for key, value in (d or {}).items():
        if isinstance(value, dict):
            for k2, v2 in value.items():
                if not isinstance(v2, (dict, list)):
                    flat[k2] = v2
        elif not isinstance(value, list):
            flat[key] = value
    return flat
