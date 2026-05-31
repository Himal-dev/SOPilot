"""The tool-connector contract (MCP-shaped).

This is a framework-agnostic seam: the planner depends only on these types, not
on any MCP SDK. A real connector would wrap an MCP client/transport (stdio or
HTTP) and forward calls; the shape mirrors MCP's tools/resources/prompts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """A callable tool advertised by a server."""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    server: str = ""


class ResourceSpec(BaseModel):
    """A readable resource advertised by a server."""

    uri: str
    name: str = ""
    description: str = ""
    server: str = ""


class PromptSpec(BaseModel):
    """A reusable prompt template advertised by a server."""

    name: str
    description: str = ""
    server: str = ""


class ToolCallResult(BaseModel):
    ok: bool = True
    tool: str = ""
    server: str = ""
    result: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""


@runtime_checkable
class MCPConnector(Protocol):
    """Contract for a single MCP-style server connection.

    Discovery (``list_*``) lets the router build a catalog without hardcoding
    tools. ``call_tool`` / ``read_resource`` perform the work.
    """

    name: str

    def list_tools(self) -> List[ToolSpec]:
        ...

    def list_resources(self) -> List[ResourceSpec]:
        ...

    def list_prompts(self) -> List[PromptSpec]:
        ...

    def call_tool(self, tool: str, arguments: Dict[str, Any]) -> ToolCallResult:
        ...

    def read_resource(self, uri: str) -> ToolCallResult:
        ...
