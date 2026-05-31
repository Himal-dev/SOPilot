"""SOPilot command-line interface.

Usage::

    python -m sopilot run examples/support_runbook_agent
    python -m sopilot run examples/rental_move_in_agent --interactive
    python -m sopilot compile examples/car_inspection_agent
    python -m sopilot manifest examples/plant_doctor_agent

The ``run`` command compiles the SOP, runs the planner over the state graph on
``sample_inputs/``, auto-approves HITL checkpoints (unless ``--interactive``),
writes structured output into ``sample_outputs/``, and prints the evidence
ledger. It runs end-to-end with no API keys.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from core.sop_compiler import compile_sop
from sopilot.config import load_agent_config
from sopilot.runner import run_agent
from sopilot.scaffold import build_agent_manifest


def _print_header(title: str) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


def _event_printer(event: str, payload: Dict[str, Any]) -> None:
    print(f"  [{event}] {json.dumps(payload)}")


def cmd_run(args: argparse.Namespace) -> int:
    agent_dir = Path(args.agent_dir)
    _print_header(f"SOPilot run: {agent_dir.name}")
    print(f"  interactive   : {args.interactive}")
    print(f"  checkpointer  : {args.checkpointer}")

    result = run_agent(
        agent_dir,
        interactive=args.interactive,
        checkpointer_backend=args.checkpointer,
        db_path=args.db,
        output_path=args.out,
        on_event=_event_printer,
    )

    state = result.state
    wf = result.workflow

    _print_header("Compiled workflow")
    print(f"  goal           : {wf.goal}")
    print(f"  sop_version    : {wf.sop_version}")
    print(f"  source         : {wf.source}")
    print(f"  steps          : {[s.id for s in wf.steps]}")
    print(f"  human_review   : {[p.id for p in wf.human_review_points]}")
    print(f"  tools_needed   : {wf.tools_needed}")

    _print_header("HITL checkpoints")
    if result.review_events:
        for ev in result.review_events:
            print(
                f"  - {ev['review_point']} ({ev['trigger']}, risk={ev['risk']}) "
                f"-> {ev['decision']} by {ev['reviewer']}"
            )
    else:
        print("  (none triggered)")

    _print_header("Evidence ledger")
    for rec in state.evidence:
        print(
            f"  - [{rec['id']}] {rec['claim']} "
            f"(conf={rec['confidence']:.2f}, model={rec['model']}, "
            f"confirmed={rec['human_confirmed']}) evidence={rec['evidence']}"
        )

    _print_header("Result")
    print(f"  status         : {state.status}")
    print(f"  completed_steps: {state.completed_steps}")
    print(f"  risks          : {len(state.risks)}")
    if result.output_path:
        print(f"  output written : {result.output_path}")
    if state.final_output is not None:
        print("  final_output.summary:")
        for line in str(state.final_output.get("summary", "")).splitlines():
            print(f"    {line}")

    return 0 if state.status == "completed" else 2


def cmd_compile(args: argparse.Namespace) -> int:
    config = load_agent_config(args.agent_dir)
    sop_text = config.resolve(config.sop).read_text()
    output_schema = None
    if config.output_schema.strip().lower() != "suggest":
        schema_path = config.resolve(config.output_schema)
        if schema_path.exists():
            output_schema = json.loads(schema_path.read_text())
    workflow = compile_sop(
        sop_text,
        sop_version=config.sop_version,
        output_schema=output_schema,
        compiler_config=config.model.compiler.model_dump(),
    )
    print(json.dumps(workflow.model_dump(), indent=2))
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    manifest = build_agent_manifest(args.agent_dir)
    print(json.dumps(manifest.model_dump(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sopilot", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Compile + run an SOP agent end-to-end.")
    run_p.add_argument("agent_dir", help="Path to an examples/<name> directory.")
    run_p.add_argument(
        "--interactive", action="store_true",
        help="Prompt a human at HITL checkpoints (default: auto-approve).",
    )
    run_p.add_argument(
        "--checkpointer", choices=["sqlite", "memory"], default="sqlite",
        help="LangGraph checkpointer backend (default: sqlite).",
    )
    run_p.add_argument("--db", default=None, help="SQLite checkpoint DB path.")
    run_p.add_argument("--out", default=None, help="Where to write the output JSON.")
    run_p.set_defaults(func=cmd_run)

    compile_p = sub.add_parser("compile", help="Compile an SOP and print the workflow.")
    compile_p.add_argument("agent_dir", help="Path to an examples/<name> directory.")
    compile_p.set_defaults(func=cmd_compile)

    manifest_p = sub.add_parser(
        "manifest",
        help="Print app-facing metadata: media requirements, provider status, and review points.",
    )
    manifest_p.add_argument("agent_dir", help="Path to an examples/<name> directory.")
    manifest_p.set_defaults(func=cmd_manifest)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
