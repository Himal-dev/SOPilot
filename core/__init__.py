"""SOPilot core: framework-agnostic seams for the SOP-driven agent scaffold.

The packages in ``core`` define our own contracts (state schema, adapter
contract, tool-connector contract, evidence ledger, human-review protocol).
LangGraph is used only inside :mod:`core.state_runtime` and :mod:`core.planner`
to wire and execute the graph, so the runtime could be swapped without touching
adapters, SOPs, or examples.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
