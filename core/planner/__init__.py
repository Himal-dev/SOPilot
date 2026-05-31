"""Planner: execute the compiled SOP over the state graph.

Owns step sequencing, modality dispatch (vision/voice/tool/reason), validation
rules, decision points, confidence-based next-action selection, and the
human-review gate. The planner builds the node functions; the graph wiring lives
in :mod:`core.state_runtime.graph`.
"""

from core.planner.planner import Planner

__all__ = ["Planner"]
