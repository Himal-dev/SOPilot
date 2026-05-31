"""Real vision adapter backed by OpenAI GPT-4o chat completions.

The HTTP call is injectable (``chat_fn``) so tests can exercise request shaping
and parsing without network access. Per-step images arrive in
``ObserveRequest.inputs["media"]`` keyed by ``step_id`` as
``{"image_b64": ..., "image_id": ..., "mime": ...}``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from core.adapters.base import (
    ActionRequest,
    ActionResult,
    Observation,
    ObserveRequest,
)

_SYSTEM = (
    "You are a careful plant-health vision assistant. Look at the image and the "
    "instruction, and respond only with a compact JSON object with keys: species, "
    "common_name, health, symptoms, severity, confidence, and summary. Confidence "
    "must be a number from 0.0 to 1.0. If the image does not clearly show plant "
    "evidence, say that in summary and set confidence below 0.3."
)


class OpenAIVisionAdapter:
    """GPT-4o-backed vision adapter satisfying the generic Adapter contract."""

    def __init__(
        self,
        *,
        name: str = "vision",
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        chat_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.name = name
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._chat_fn = chat_fn or self._default_chat_fn

    def capabilities(self) -> List[str]:
        return ["observe", "act", "capture"]

    def observe(self, request: ObserveRequest) -> Observation:
        media = (request.inputs or {}).get("media", {}) or {}
        entry = media.get(request.step_id) or {}
        image_b64 = entry.get("image_b64")
        if not image_b64:
            return Observation(
                step_id=request.step_id,
                source="vision",
                summary="No image provided for this step.",
                confidence=0.0,
                model=self.model,
            )

        mime = entry.get("mime", "image/jpeg")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.instruction or request.step_id},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_b64}"
                            },
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
            "temperature": 0,
        }
        image_id = entry.get("image_id", request.step_id)
        try:
            response = self._chat_fn(payload)
            content = _message_content(response)
            data = json.loads(content)
            confidence = _clamp_confidence(data.get("confidence", 0.5))
        except Exception as exc:
            return Observation(
                step_id=request.step_id,
                source="vision",
                summary=f"Vision call failed: {exc}",
                confidence=0.0,
                evidence_refs=[image_id],
                model=self.model,
            )

        return Observation(
            step_id=request.step_id,
            source="vision",
            content=data,
            summary=data.get("summary", "") or request.instruction,
            confidence=confidence,
            evidence_refs=[image_id],
            model=self.model,
        )

    def act(self, request: ActionRequest) -> ActionResult:
        return ActionResult(ok=True, detail=f"vision noop '{request.action}'")

    def _default_chat_fn(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))


def _message_content(response: Dict[str, Any]) -> str:
    message = response["choices"][0]["message"]
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        content = "\n".join(parts)
    if not isinstance(content, str) or not content.strip():
        detail = message.get("refusal") or "OpenAI returned no vision JSON content."
        raise RuntimeError(str(detail).rstrip(".") + ".")
    return _strip_json_fence(content.strip())


def _strip_json_fence(content: str) -> str:
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return content


def _clamp_confidence(raw: Any) -> float:
    if isinstance(raw, str):
        mapped = {
            "very low": 0.1,
            "low": 0.25,
            "medium": 0.5,
            "moderate": 0.5,
            "high": 0.75,
            "very high": 0.9,
        }.get(raw.strip().lower())
        if mapped is not None:
            return mapped
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))
