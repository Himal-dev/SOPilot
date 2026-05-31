"""Server discovery + planner-driven tool selection.

The router aggregates one or more :class:`~core.tool_router.contract.MCPConnector`
instances, builds a tool catalog, and selects tools for a step's
``tools_needed`` declarations. There are no hardcoded tools here -- everything
comes from connector discovery.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.tool_router.contract import (
    MCPConnector,
    ResourceSpec,
    ToolCallResult,
    ToolSpec,
)


class ToolRouter:
    """Routes tool calls to the connector that advertises them."""

    def __init__(self, connectors: Optional[List[MCPConnector]] = None) -> None:
        self._connectors: List[MCPConnector] = list(connectors or [])

    def add_connector(self, connector: MCPConnector) -> None:
        self._connectors.append(connector)

    def discover_tools(self) -> List[ToolSpec]:
        """Return the union of tools advertised by all connectors."""
        tools: List[ToolSpec] = []
        for c in self._connectors:
            tools.extend(c.list_tools())
        return tools

    def discover_resources(self) -> List[ResourceSpec]:
        resources: List[ResourceSpec] = []
        for c in self._connectors:
            resources.extend(c.list_resources())
        return resources

    def select_tool(self, requirement: str) -> Optional[ToolSpec]:
        """Pick the best tool for a ``tools_needed`` requirement.

        Selection is intentionally simple and deterministic: exact name match
        first, then a substring/keyword match against tool name + description.
        A smarter planner could rank by input-schema fit or use an LLM, but the
        contract (requirement string -> ToolSpec) stays the same.
        """
        catalog = self.discover_tools()
        req = (requirement or "").strip().lower()
        if not req:
            return None
        for tool in catalog:
            if tool.name.lower() == req:
                return tool
        for tool in catalog:
            haystack = f"{tool.name} {tool.description}".lower()
            if req in haystack or any(
                tok and tok in haystack for tok in req.replace("-", " ").split("_")
            ):
                return tool
        return None

    def call(
        self, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> ToolCallResult:
        """Call ``tool_name`` on whichever connector advertises it."""
        for c in self._connectors:
            if any(t.name == tool_name for t in c.list_tools()):
                return c.call_tool(tool_name, arguments or {})
        return ToolCallResult(
            ok=False, tool=tool_name, error=f"no connector advertises '{tool_name}'"
        )

    @property
    def server_names(self) -> List[str]:
        return [c.name for c in self._connectors]
