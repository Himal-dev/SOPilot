"""Voice adapter: ask/answer and speak prompts for a step.

Ships a deterministic reference stub plus an ElevenLabs adapter (STT + TTS).
Both satisfy the :class:`~core.adapters.base.Adapter` contract.
"""

from core.voice_adapter.adapter import VoiceStubAdapter
from core.voice_adapter.elevenlabs_adapter import ElevenLabsVoiceAdapter

__all__ = ["VoiceStubAdapter", "ElevenLabsVoiceAdapter"]
