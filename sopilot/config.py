"""Load and validate ``agent_config.yaml`` for an example agent.

The config is the *only* thing (alongside ``sop.md`` and ``output_schema.json``)
that differs between agents -- nothing in ``core`` changes. It wires: which SOP,
the output schema (or "suggest"), enabled adapters, MCP servers, HITL policy, and
model/budget settings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class AdapterConfig(BaseModel):
    enabled: bool = True
    # Which adapter implementation to use: "stub" (default), "openai", "elevenlabs".
    provider: str = "stub"
    # Path (relative to the agent dir) to a per-step cue book for the stub.
    cues: Optional[str] = None
    # Env var checked before selecting a live provider. Defaults are provider-specific.
    api_key_env: Optional[str] = None
    # Fail instead of silently falling back to a stub when this adapter cannot go live.
    require_live: bool = False
    # Per-adapter override for runtime.allow_stub_fallback.
    stub_fallback: Optional[bool] = None


class MCPServerConfig(BaseModel):
    name: str
    type: str = "stub"
    # Path (relative to the agent dir) to a catalog JSON:
    # {tools, resources, prompts, responses}.
    catalog: Optional[str] = None
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    prompts: List[Dict[str, Any]] = Field(default_factory=list)
    responses: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class HITLConfig(BaseModel):
    auto_approve: bool = True
    reject_triggers: List[str] = Field(default_factory=list)
    reject_above_risk: Optional[str] = None
    reviewer: str = "auto"


class CompilerConfig(BaseModel):
    use_llm: bool = False
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"


class ModelConfig(BaseModel):
    compiler: CompilerConfig = Field(default_factory=CompilerConfig)
    max_steps: int = 100
    budget_usd: float = 0.0


class RuntimeConfig(BaseModel):
    """Cross-cutting runtime policy shared by CLI, apps, and hosted demos."""

    require_live_adapters: bool = False
    allow_stub_fallback: bool = True
    auto_finalize_on_start: bool = False
    auto_finalize_reviewer: str = "auto"


class AgentConfig(BaseModel):
    name: str
    description: str = ""
    sop: str = "sop.md"
    sop_version: str = "v1"
    # "suggest" or a path (relative to agent dir) to an output_schema.json.
    output_schema: str = "output_schema.json"
    adapters: Dict[str, AdapterConfig] = Field(default_factory=dict)
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    hitl: HITLConfig = Field(default_factory=HITLConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    # Populated at load time; not part of the YAML.
    agent_dir: Path = Field(default=Path("."), exclude=True)

    def resolve(self, relative: str) -> Path:
        return (self.agent_dir / relative).resolve()


def load_agent_config(agent_dir: str | Path) -> AgentConfig:
    """Load ``agent_config.yaml`` from an example directory."""
    agent_path = Path(agent_dir).resolve()
    config_path = agent_path / "agent_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"missing agent_config.yaml in {agent_path}")
    data = yaml.safe_load(config_path.read_text()) or {}
    config = AgentConfig.model_validate(data)
    config.agent_dir = agent_path
    return config


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())
