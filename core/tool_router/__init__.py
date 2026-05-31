"""Tool/MCP connector layer (no hardcoded tools).

MCP is the standard direction: servers expose tools, resources, and prompts. The
:class:`~core.tool_router.contract.MCPConnector` contract abstracts a server; the
:class:`~core.tool_router.router.ToolRouter` discovers servers and lets the
planner select tools per the SOP's ``tools_needed``. A local stub connector
ships so examples run without any real MCP server.
"""

from core.tool_router.contract import (
    MCPConnector,
    PromptSpec,
    ResourceSpec,
    ToolCallResult,
    ToolSpec,
)
from core.tool_router.router import ToolRouter
from core.tool_router.stub_connector import StubMCPConnector

__all__ = [
    "MCPConnector",
    "PromptSpec",
    "ResourceSpec",
    "ToolCallResult",
    "ToolSpec",
    "ToolRouter",
    "StubMCPConnector",
]
