"""Fill an output schema from the central state and evidence ledger."""

from __future__ import annotations

from typing import Any, Dict, List

from core.evidence_ledger import EvidenceLedger
from core.state_runtime.state import State


def _summarize(state: State) -> str:
    parts: List[str] = []
    for obs in state.observations:
        summary = obs.get("summary")
        if summary:
            parts.append(f"- {summary}")
    if not parts:
        return f"Completed {len(state.completed_steps)} step(s) for {state.goal}."
    header = (
        f"{state.goal}: completed {len(state.completed_steps)} step(s), "
        f"{len(state.risks)} risk(s) flagged."
    )
    return header + "\n" + "\n".join(parts)


def generate_output(
    state: State, output_schema: Dict[str, Any]
) -> Dict[str, Any]:
    """Produce the structured output dict per ``output_schema``.

    For each top-level schema property we try to fill from ``step_outputs``;
    ``summary`` and ``completed`` are computed; unknown fields are left absent.
    The full evidence ledger is attached under ``_evidence`` and per-field
    evidence references are preserved so every output value is auditable.
    """
    ledger = EvidenceLedger.from_state(state.evidence)
    properties: Dict[str, Any] = (output_schema or {}).get("properties", {})

    output: Dict[str, Any] = {}
    for key in properties:
        if key == "summary":
            output["summary"] = _summarize(state)
        elif key == "completed":
            output["completed"] = state.status == "completed"
        elif key in state.step_outputs:
            output[key] = state.step_outputs[key]

    # If the schema is empty/unknown, still emit a useful structured result.
    if not properties:
        output = {
            "summary": _summarize(state),
            "completed": state.status == "completed",
            "fields": dict(state.step_outputs),
        }

    output["_meta"] = {
        "goal": state.goal,
        "sop_version": state.sop_version,
        "status": state.status,
        "completed_steps": list(state.completed_steps),
        "risks": list(state.risks),
        "human_overrides": list(state.human_overrides),
    }
    output["_evidence"] = ledger.to_list()
    return output
