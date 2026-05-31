"""State runtime: the typed central state + the LangGraph graph wiring.

The central :class:`~core.state_runtime.state.State` is our own Pydantic schema
(the framework-agnostic seam). :mod:`core.state_runtime.graph` is the only place
that knows about LangGraph: it builds the ``StateGraph`` and wires a checkpointer
(SQLite by default) so runs can interrupt -> inspect -> approve/edit/reject ->
resume.

Graph helpers (``build_graph``, ``compile_graph``, ``build_checkpointer``) live
in :mod:`core.state_runtime.graph`; import them from there to avoid a circular
import with the planner.
"""

from core.state_runtime.state import State

__all__ = ["State"]
