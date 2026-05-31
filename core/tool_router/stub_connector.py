"""A local, in-process MCP connector for dry-runs and tests.

Configured with a catalog of tools/resources/prompts and a table of canned
responses keyed by tool name. This stands in for a real MCP server so the
planner's tool-selection and tool-calling paths run without any network.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.tool_router.contract import (
    PromptSpec,
    ResourceSpec,
    ToolCallResult,
    ToolSpec,
)


class StubMCPConnector:
    """In-memory MCP connector backed by a static catalog + canned responses."""

    def __init__(
        self,
        name: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        resources: Optional[List[Dict[str, Any]]] = None,
        prompts: Optional[List[Dict[str, Any]]] = None,
        responses: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.name = name
        self._tools = [
            ToolSpec(server=name, **t) if "server" not in t else ToolSpec(**t)
            for t in (tools or [])
        ]
        self._resources = [
            ResourceSpec(server=name, **r) for r in (resources or [])
        ]
        self._prompts = [PromptSpec(server=name, **p) for p in (prompts or [])]
        # responses: {tool_name: canned_result_dict}
        self._responses: Dict[str, Dict[str, Any]] = responses or {}

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools)

    def list_resources(self) -> List[ResourceSpec]:
        return list(self._resources)

    def list_prompts(self) -> List[PromptSpec]:
        return list(self._prompts)

    def call_tool(self, tool: str, arguments: Dict[str, Any]) -> ToolCallResult:
        known = {t.name for t in self._tools}
        if tool not in known:
            return ToolCallResult(
                ok=False, tool=tool, server=self.name,
                error=f"unknown tool '{tool}' on server '{self.name}'",
            )
        canned = self._responses.get(tool, {})
        # Echo arguments so the result is self-describing/auditable.
        result = {"arguments": arguments, **canned}
        return ToolCallResult(ok=True, tool=tool, server=self.name, result=result)

    def read_resource(self, uri: str) -> ToolCallResult:
        match = next((r for r in self._resources if r.uri == uri), None)
        if match is None:
            return ToolCallResult(
                ok=False, server=self.name, error=f"unknown resource '{uri}'"
            )
        canned = self._responses.get(uri, {})
        return ToolCallResult(
            ok=True, server=self.name, result={"uri": uri, **canned}
        )
