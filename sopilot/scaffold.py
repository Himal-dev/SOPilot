"""Reusable scaffolding helpers for turning SOP agents into products.

These helpers expose runtime facts that early demos kept re-discovering in app
code: what media a workflow needs, which providers can run live, and whether a
configured app will fall back to stubs or fail closed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, Field

from core.sop_compiler import compile_sop
from core.sop_compiler.workflow import WorkflowStep
from sopilot.config import AdapterConfig, AgentConfig, load_agent_config, load_json


DEFAULT_PROVIDER_ENV = {
    ("vision", "openai"): "OPENAI_API_KEY",
    ("voice", "elevenlabs"): "ELEVENLABS_API_KEY",
}


class AdapterStatus(BaseModel):
    modality: str
    enabled: bool
    provider: str
    live_required: bool = False
    live_ready: bool = False
    fallback_allowed: bool = True
    fallback_to_stub: bool = False
    missing_env: list[str] = Field(default_factory=list)
    reason: str = ""


class MediaRequirement(BaseModel):
    step_id: str
    modality: str
    title: str
    instruction: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    drilldown_questions: list[str] = Field(default_factory=list)
    min_confidence: float = 0.4
    required: bool = True


class AgentManifest(BaseModel):
    name: str
    description: str = ""
    sop_version: str
    goal: str
    adapters: list[AdapterStatus]
    media_requirements: list[MediaRequirement]
    review_points: list[dict[str, Any]]
    output_fields: list[str]
    runtime: dict[str, Any]


class ProviderConfigurationError(RuntimeError):
    """Raised when config requires live providers that cannot be initialized."""


def provider_env_key(modality: str, adapter_cfg: AdapterConfig) -> Optional[str]:
    if adapter_cfg.api_key_env:
        return adapter_cfg.api_key_env
    return DEFAULT_PROVIDER_ENV.get((modality, (adapter_cfg.provider or "stub").lower()))


def has_agent_transcript(media: Optional[Dict[str, Any]]) -> bool:
    return any(
        isinstance(entry, dict) and bool(str(entry.get("transcript", "")).strip())
        for entry in (media or {}).values()
    )


def adapter_status(
    modality: str,
    adapter_cfg: AdapterConfig,
    config: AgentConfig,
    *,
    env: Optional[Mapping[str, str]] = None,
    media: Optional[Dict[str, Any]] = None,
) -> AdapterStatus:
    env = env or os.environ
    provider = (adapter_cfg.provider or "stub").lower()
    live_required = bool(adapter_cfg.require_live or config.runtime.require_live_adapters)
    fallback_allowed = (
        config.runtime.allow_stub_fallback
        if adapter_cfg.stub_fallback is None
        else bool(adapter_cfg.stub_fallback)
    )

    if not adapter_cfg.enabled:
        return AdapterStatus(
            modality=modality,
            enabled=False,
            provider=provider,
            fallback_allowed=fallback_allowed,
            reason="Adapter disabled.",
        )

    if provider in {"stub", "local", "fixture"}:
        return AdapterStatus(
            modality=modality,
            enabled=True,
            provider=provider,
            live_required=live_required,
            live_ready=True,
            fallback_allowed=fallback_allowed,
            reason="Using deterministic local adapter.",
        )

    if modality == "voice" and provider == "elevenlabs" and has_agent_transcript(media):
        return AdapterStatus(
            modality=modality,
            enabled=True,
            provider=provider,
            live_required=live_required,
            live_ready=True,
            fallback_allowed=fallback_allowed,
            reason="Using hosted voice-agent transcript; STT key is not required.",
        )

    env_key = provider_env_key(modality, adapter_cfg)
    missing = [env_key] if env_key and not env.get(env_key) else []
    live_ready = not missing
    fallback_to_stub = bool(missing and fallback_allowed and not live_required)
    reason = (
        f"Missing {', '.join(missing)}."
        if missing
        else f"Live provider '{provider}' is configured."
    )

    return AdapterStatus(
        modality=modality,
        enabled=True,
        provider=provider,
        live_required=live_required,
        live_ready=live_ready,
        fallback_allowed=fallback_allowed,
        fallback_to_stub=fallback_to_stub,
        missing_env=missing,
        reason=reason,
    )


def assert_live_provider_status(status: AdapterStatus) -> None:
    if status.enabled and status.live_required and not status.live_ready:
        missing = ", ".join(status.missing_env) or "provider configuration"
        raise ProviderConfigurationError(
            f"{status.modality} adapter requires live provider '{status.provider}', "
            f"but {missing} is not configured."
        )
    if status.enabled and not status.live_ready and not status.fallback_to_stub:
        missing = ", ".join(status.missing_env) or "provider configuration"
        raise ProviderConfigurationError(
            f"{status.modality} adapter provider '{status.provider}' is unavailable "
            f"and stub fallback is disabled; missing {missing}."
        )


def media_requirement_from_step(step: WorkflowStep) -> Optional[MediaRequirement]:
    if step.modality not in {"vision", "voice"}:
        return None
    return MediaRequirement(
        step_id=step.id,
        modality=step.modality,
        title=step.title,
        instruction=step.instruction,
        evidence_refs=list(step.required_evidence),
        produces=list(step.produces),
        drilldown_questions=list(step.drilldown_questions),
        min_confidence=step.min_confidence,
        required=True,
    )


def build_agent_manifest(
    agent_dir: str | Path,
    *,
    env: Optional[Mapping[str, str]] = None,
    media: Optional[Dict[str, Any]] = None,
) -> AgentManifest:
    config = load_agent_config(agent_dir)
    output_schema = None
    if config.output_schema.strip().lower() != "suggest":
        schema_path = config.resolve(config.output_schema)
        output_schema = load_json(schema_path) if schema_path.exists() else None
    workflow = compile_sop(
        config.resolve(config.sop).read_text(),
        sop_version=config.sop_version,
        output_schema=output_schema,
        compiler_config=config.model.compiler.model_dump(),
    )
    output_fields = list((workflow.output_schema.get("properties") or {}).keys())
    return AgentManifest(
        name=config.name,
        description=config.description,
        sop_version=config.sop_version,
        goal=workflow.goal,
        adapters=[
            adapter_status(modality, adapter_cfg, config, env=env, media=media)
            for modality, adapter_cfg in config.adapters.items()
        ],
        media_requirements=[
            req
            for req in (media_requirement_from_step(step) for step in workflow.steps)
            if req is not None
        ],
        review_points=[point.model_dump() for point in workflow.human_review_points],
        output_fields=output_fields,
        runtime=config.runtime.model_dump(),
    )
