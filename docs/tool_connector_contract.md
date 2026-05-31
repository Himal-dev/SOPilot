# Tool-connector contract (MCP-shaped)

SOPilot has **no hardcoded tools**. The planner depends only on the contract in
`core/tool_router/contract.py`; concrete connectors wrap a real MCP
client/transport (stdio or HTTP) or, for dry-runs, a local stub.

## `MCPConnector` (Protocol)

```python
class MCPConnector(Protocol):
    name: str
    def list_tools(self) -> list[ToolSpec]: ...
    def list_resources(self) -> list[ResourceSpec]: ...
    def list_prompts(self) -> list[PromptSpec]: ...
    def call_tool(self, tool: str, arguments: dict) -> ToolCallResult: ...
    def read_resource(self, uri: str) -> ToolCallResult: ...
```

This mirrors MCP's three primitives:

- **tools** — callable functions reaching DBs/APIs/computation (`ToolSpec` has
  `name`, `description`, `input_schema`, `server`).
- **resources** — readable data (`ResourceSpec` has `uri`, `name`, ...).
- **prompts** — reusable prompt templates (`PromptSpec`).

A call returns a `ToolCallResult{ok, tool, server, result, error}`.

## The router

`core/tool_router/router.py::ToolRouter` aggregates connectors and provides:

- `discover_tools()` / `discover_resources()` — union across connectors.
- `select_tool(requirement)` — deterministic selection for a step's
  `tools_needed` entry: exact name match first, then keyword/substring match
  against name + description. (A smarter planner could rank by input-schema fit
  or use an LLM; the contract — `requirement -> ToolSpec` — stays the same.)
- `call(tool_name, arguments)` — routes to whichever connector advertises it.

## Wiring a server in `agent_config.yaml`

```yaml
mcp_servers:
  - name: support_stack
    type: stub                       # local in-process connector
    catalog: sample_inputs/mcp_support_stack.json
```

The catalog JSON has `{tools, resources, prompts, responses}`, where `responses`
maps a tool name to a canned result dict (used by the stub so dry-runs are
deterministic). See `examples/support_runbook_agent/sample_inputs/`.

## Writing a real connector

Implement the `MCPConnector` protocol around an MCP SDK:

```python
class MyMCPConnector:
    name = "crm"
    def __init__(self, client): self._client = client
    def list_tools(self):
        return [ToolSpec(server=self.name, **t) for t in self._client.list_tools()]
    def call_tool(self, tool, arguments):
        out = self._client.call(tool, arguments)
        return ToolCallResult(ok=True, tool=tool, server=self.name, result=out)
    # ... list_resources / list_prompts / read_resource
```

Then register it in `sopilot/runner.py::_build_tool_router` (or extend the
config to point at a server command/URL). Nothing in `core/planner` changes —
the planner only ever sees `select_tool` + `call`.
