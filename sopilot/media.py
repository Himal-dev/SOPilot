"""Normalize collected app media into SOPilot runner inputs.

Apps usually collect evidence by user-facing field names such as
``whole_plant_photo`` or ``care_habits_audio``. Adapters consume media keyed by
compiled ``step_id``. This module bridges that gap using the agent manifest.
"""

from __future__ import annotations

import base64
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, Field

from sopilot.scaffold import AgentManifest, MediaRequirement


class MediaAsset(BaseModel):
    """One collected media or transcript artifact from an app surface."""

    field: str
    data: Optional[bytes] = None
    image_b64: str = ""
    audio_path: str = ""
    transcript: str = ""
    mime: str = ""
    filename: str = ""
    recording_id: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    confidence: Optional[float] = None

    @classmethod
    def from_bytes(
        cls,
        field: str,
        data: bytes,
        *,
        mime: str = "",
        filename: str = "",
    ) -> "MediaAsset":
        return cls(field=field, data=data, mime=mime, filename=filename)

    @classmethod
    def from_transcript(
        cls,
        field: str,
        transcript: str,
        *,
        content: Optional[dict[str, Any]] = None,
        recording_id: str = "",
        model: str = "app-transcript",
        confidence: float = 0.9,
    ) -> "MediaAsset":
        return cls(
            field=field,
            transcript=transcript,
            content=content or {},
            recording_id=recording_id or field,
            model=model,
            confidence=confidence,
        )


def build_media_map(
    manifest_or_requirements: AgentManifest | Iterable[MediaRequirement],
    assets: Mapping[str, MediaAsset | Mapping[str, Any] | None],
    *,
    temp_dir: str | Path | None = None,
    filename_prefix: str = "sopilot_media",
) -> dict[str, dict[str, Any]]:
    """Return adapter-ready ``media`` keyed by compiled step id."""

    media: dict[str, dict[str, Any]] = {}
    for requirement in _requirements(manifest_or_requirements):
        asset = _first_asset_for_requirement(requirement, assets)
        if asset is None:
            continue
        if requirement.modality == "vision":
            payload = _vision_payload(requirement, asset)
        elif requirement.modality == "voice":
            payload = _voice_payload(requirement, asset, temp_dir, filename_prefix)
        else:
            continue
        if payload:
            media[requirement.step_id] = payload
    return media


def missing_required_media(
    manifest_or_requirements: AgentManifest | Iterable[MediaRequirement],
    media: Mapping[str, Any],
) -> list[MediaRequirement]:
    """Return required media requirements not present in an adapter media map."""

    return [
        requirement
        for requirement in _requirements(manifest_or_requirements)
        if requirement.required and requirement.step_id not in media
    ]


def _requirements(
    manifest_or_requirements: AgentManifest | Iterable[MediaRequirement],
) -> list[MediaRequirement]:
    if isinstance(manifest_or_requirements, AgentManifest):
        return list(manifest_or_requirements.media_requirements)
    return list(manifest_or_requirements)


def _first_asset_for_requirement(
    requirement: MediaRequirement,
    assets: Mapping[str, MediaAsset | Mapping[str, Any] | None],
) -> Optional[MediaAsset]:
    keys = [*requirement.evidence_refs, requirement.step_id, *requirement.produces]
    for key in keys:
        raw = assets.get(key)
        if raw is None:
            continue
        asset = raw if isinstance(raw, MediaAsset) else MediaAsset.model_validate(raw)
        if _asset_has_payload(asset):
            return asset
    return None


def _asset_has_payload(asset: MediaAsset) -> bool:
    return bool(asset.data or asset.image_b64 or asset.audio_path or asset.transcript.strip())


def _vision_payload(requirement: MediaRequirement, asset: MediaAsset) -> dict[str, Any]:
    image_b64 = asset.image_b64
    if not image_b64 and asset.data:
        image_b64 = base64.b64encode(asset.data).decode()
    if not image_b64:
        return {}
    image_id = asset.field or (
        requirement.evidence_refs[0] if requirement.evidence_refs else requirement.step_id
    )
    return {
        "image_b64": image_b64,
        "image_id": image_id,
        "mime": asset.mime or "image/jpeg",
    }


def _voice_payload(
    requirement: MediaRequirement,
    asset: MediaAsset,
    temp_dir: str | Path | None,
    filename_prefix: str,
) -> dict[str, Any]:
    transcript = asset.transcript.strip()
    recording_id = asset.recording_id or asset.field or requirement.step_id
    if transcript:
        payload: dict[str, Any] = {
            "transcript": transcript,
            "recording_id": recording_id,
            "content": dict(asset.content),
            "model": asset.model or "app-transcript",
            "confidence": 0.9 if asset.confidence is None else asset.confidence,
        }
        return payload

    audio_path = asset.audio_path
    if not audio_path and asset.data:
        audio_path = _write_temp_media(asset, temp_dir=temp_dir, filename_prefix=filename_prefix)
    if not audio_path:
        return {}
    return {"audio_path": audio_path, "recording_id": recording_id}


def _write_temp_media(
    asset: MediaAsset,
    *,
    temp_dir: str | Path | None,
    filename_prefix: str,
) -> str:
    directory = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(asset.filename or "audio.bin").suffix or ".bin"
    path = directory / f"{filename_prefix}_{uuid.uuid4().hex}{suffix}"
    path.write_bytes(asset.data or b"")
    return str(path)
