"""Pluggable perception/actuation adapter contract.

Adapters are how the platform *senses* and *acts* on the world without the core
knowing anything about a specific model or device. A vision adapter might wrap a
VLM + camera; a voice adapter might wrap STT/TTS. Any implementation that
satisfies :class:`~core.adapters.base.Adapter` can be plugged in via config.
"""

from core.adapters.base import (
    Adapter,
    ActionRequest,
    ActionResult,
    Observation,
    ObserveRequest,
)

__all__ = [
    "Adapter",
    "ActionRequest",
    "ActionResult",
    "Observation",
    "ObserveRequest",
]
