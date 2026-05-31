"""LangGraph wiring -- the ONLY module that imports LangGraph graph primitives.

Builds a ``StateGraph`` over the central :class:`State` and a checkpointer
(SQLite by default, in-memory optional). The planner supplies node functions and
routers; this module just connects them. Swapping runtimes means rewriting this
file and :func:`build_checkpointer` -- nothing else in ``core`` changes.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional, Tuple

from langgraph.graph import END, START, StateGraph

from core.planner.planner import (
    EXECUTE,
    FINALIZE,
    PLAN,
    REVIEW,
    Planner,
)
from core.state_runtime.state import State


def build_graph(planner: Planner):
    """Assemble the compiled LangGraph (without a checkpointer attached).

    Use :func:`compile_graph` to attach a checkpointer and get a runnable graph.
    """
    graph = StateGraph(State)
    graph.add_node(PLAN, planner.plan_node)
    graph.add_node(EXECUTE, planner.execute_node)
    graph.add_node(REVIEW, planner.review_node)
    graph.add_node(FINALIZE, planner.finalize_node)

    graph.add_edge(START, PLAN)
    graph.add_conditional_edges(
        PLAN, planner.route_after_plan, {EXECUTE: EXECUTE, FINALIZE: FINALIZE}
    )
    graph.add_conditional_edges(
        EXECUTE, planner.route_after_execute, {REVIEW: REVIEW, PLAN: PLAN}
    )
    graph.add_conditional_edges(
        REVIEW, planner.route_after_review, {PLAN: PLAN, FINALIZE: FINALIZE}
    )
    graph.add_edge(FINALIZE, END)
    return graph


@contextlib.contextmanager
def build_checkpointer(
    backend: str = "sqlite", path: str = ":memory:"
) -> Iterator[Any]:
    """Yield a checkpointer.

    * ``sqlite`` (default): durable, enables interrupt/inspect/resume across
      process restarts. ``path`` is a file path or ``:memory:``.
    * ``memory``: in-process only (fast tests).

    Provided as a context manager because :class:`SqliteSaver` owns a DB
    connection that must be closed.
    """
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        yield MemorySaver()
        return

    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(path) as saver:
        yield saver


def compile_graph(planner: Planner, checkpointer: Any):
    """Compile the graph with a checkpointer so HITL interrupts persist."""
    return build_graph(planner).compile(checkpointer=checkpointer)
