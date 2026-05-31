# ADR-0005: MCP as the tool-connector standard

- Status: Accepted
- Date: 2026-05-29

## Context

SOPs need to reach the outside world: CRMs, databases, pricing APIs, document
extraction, ticketing, knowledge bases. Hardcoding tools into the core would
break the genericity promise (adding capability would mean changing `core/`).

## Decision

Standardize on **MCP-shaped connectors**. `core/tool_router/contract.py` defines
an `MCPConnector` protocol exposing MCP's three primitives — **tools**,
**resources**, **prompts** — plus `call_tool`/`read_resource`. The `ToolRouter`
discovers servers, and the planner selects tools per a step's `tools_needed`.
There are no hardcoded tools. A local `StubMCPConnector` ships so examples run
offline; real connectors wrap an MCP client/transport.

## Options assessment

- **MCP connector contract (chosen):** an emerging, model-agnostic standard;
  servers are reusable across agents; discovery keeps the core tool-free.
- **Bespoke per-tool Python functions:** fast to start, but every new capability
  edits the core and isn't reusable across agents.
- **LangChain Tools only:** convenient in-ecosystem, but couples tools to a
  framework; we keep our own contract and can *adapt* LangChain/MCP behind it.

## Consequences

- Adding a capability = adding/registering an MCP server in `agent_config.yaml`,
  not editing `core/`.
- The contract is our seam: real MCP SDKs, LangChain tools, or plain HTTP can all
  be adapted to `MCPConnector` without touching the planner.
- Tool selection is currently deterministic (name/keyword match); it can be
  upgraded to schema-fit ranking or LLM selection behind the same interface.
