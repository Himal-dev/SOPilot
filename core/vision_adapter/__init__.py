"""Vision adapter: see the world for a step.

Ships a deterministic reference stub plus a GPT-4o adapter. Both satisfy
:class:`~core.adapters.base.Adapter`.
"""

from core.vision_adapter.adapter import VisionStubAdapter
from core.vision_adapter.openai_adapter import OpenAIVisionAdapter

__all__ = ["VisionStubAdapter", "OpenAIVisionAdapter"]
