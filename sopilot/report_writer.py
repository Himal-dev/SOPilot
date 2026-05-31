"""Reusable JSON report-writing prompt and model client helpers."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable, Mapping, Optional

from pydantic import BaseModel, Field


class ReportWriterError(RuntimeError):
    """Raised when a report model response cannot be parsed or validated."""


class ReportPromptSpec(BaseModel):
    name: str = "evidence_report"
    expert_role: str
    task: str
    output_contract: str
    evidence_policy: str = (
        "Use only the provided evidence fields. Distinguish observed evidence "
        "from inference. If evidence is insufficient, state exactly what is "
        "uncertain and lower confidence."
    )
    style_rules: list[str] = Field(default_factory=list)
    api_key_env: str = "OPENAI_API_KEY"
    model_env: str = "OPENAI_REPORT_MODEL"
    default_model: str = "gpt-4o"
    max_tokens: int = 1000
    temperature: float = 0.0


def build_report_prompt_payload(
    fields: Mapping[str, Any],
    *,
    instruction: str = "",
    context: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    payload = {key: value for key, value in fields.items()}
    if instruction:
        payload["instruction"] = instruction
    if context:
        payload["context"] = dict(context)
    return payload


def build_openai_json_report_request(
    payload: Mapping[str, Any],
    spec: ReportPromptSpec,
    *,
    model: Optional[str] = None,
) -> dict[str, Any]:
    system_content = _system_prompt(spec)
    return {
        "model": model or spec.default_model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(payload)},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": spec.max_tokens,
        "temperature": spec.temperature,
    }


def write_openai_json_report(
    payload: Mapping[str, Any],
    spec: ReportPromptSpec,
    *,
    env: Optional[Mapping[str, str]] = None,
    opener: Optional[Callable[..., Any]] = None,
) -> Optional[dict[str, Any]]:
    env = env or os.environ
    api_key = env.get(spec.api_key_env, "")
    if not api_key:
        return None
    model = env.get(spec.model_env, spec.default_model)
    request_payload = build_openai_json_report_request(payload, spec, model=model)
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    call = opener or urllib.request.urlopen
    with call(req, timeout=60) as response:  # nosec B310
        body = json.loads(response.read().decode("utf-8"))
    parsed = parse_openai_json_report_response(body)
    parsed.setdefault("model", model)
    return parsed


def parse_openai_json_report_response(body: Mapping[str, Any]) -> dict[str, Any]:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ReportWriterError("OpenAI response did not include message content.") from exc
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ReportWriterError("OpenAI report response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ReportWriterError("OpenAI report response JSON must be an object.")
    return parsed


def _system_prompt(spec: ReportPromptSpec) -> str:
    sections = [
        spec.expert_role.strip(),
        spec.task.strip(),
        spec.evidence_policy.strip(),
        "Produce only compact JSON with this exact shape: " + spec.output_contract.strip(),
    ]
    sections.extend(rule.strip() for rule in spec.style_rules if rule.strip())
    return " ".join(section for section in sections if section)
