"""OpenAIVisionAdapter parses a GPT-4o JSON response into an Observation."""

import base64

from core.adapters.base import ObserveRequest
from core.vision_adapter import OpenAIVisionAdapter


def _fake_chat_fn(payload):
    import json

    content = json.dumps(
        {
            "species": "Epipremnum aureum",
            "common_name": "Pothos",
            "health": "fair",
            "symptoms": ["interveinal yellowing"],
            "severity": "mild",
            "confidence": 0.81,
            "summary": "Pothos with mild yellowing on older leaves.",
        }
    )
    return {"choices": [{"message": {"content": content}}]}


def test_observe_parses_vision_json():
    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=_fake_chat_fn)
    img = base64.b64encode(b"fake-jpeg-bytes").decode()
    req = ObserveRequest(
        step_id="capture_the_whole_plant_in_frame",
        instruction="Capture the whole plant in frame",
        inputs={
            "media": {
                "capture_the_whole_plant_in_frame": {
                    "image_b64": img,
                    "image_id": "whole_plant_photo",
                    "mime": "image/jpeg",
                }
            }
        },
    )
    obs = adapter.observe(req)
    assert obs.source == "vision"
    assert obs.model == "gpt-4o"
    assert obs.confidence == 0.81
    assert obs.content["common_name"] == "Pothos"
    assert "whole_plant_photo" in obs.evidence_refs


def test_observe_without_image_returns_low_confidence():
    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=_fake_chat_fn)
    req = ObserveRequest(step_id="s1", instruction="look", inputs={"media": {}})
    obs = adapter.observe(req)
    assert obs.confidence == 0.0
    assert "no image" in obs.summary.lower()


def test_observe_maps_text_confidence_to_numeric_value():
    def chat_fn(_payload):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"species":"Unknown","common_name":"Unknown",'
                            '"health":"unclear","symptoms":[],"severity":"low",'
                            '"confidence":"Low","summary":"Plant evidence is unclear."}'
                        )
                    }
                }
            ]
        }

    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=chat_fn)
    img = base64.b64encode(b"fake-jpeg-bytes").decode()
    req = ObserveRequest(
        step_id="capture_the_whole_plant_in_frame",
        instruction="Capture the whole plant in frame",
        inputs={
            "media": {
                "capture_the_whole_plant_in_frame": {
                    "image_b64": img,
                    "image_id": "whole_plant_photo",
                    "mime": "image/jpeg",
                }
            }
        },
    )

    obs = adapter.observe(req)

    assert obs.confidence == 0.25
    assert "whole_plant_photo" in obs.evidence_refs


def test_observe_reports_empty_model_content_cleanly():
    def chat_fn(_payload):
        return {"choices": [{"message": {"content": None}}]}

    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=chat_fn)
    img = base64.b64encode(b"fake-jpeg-bytes").decode()
    req = ObserveRequest(
        step_id="capture_the_whole_plant_in_frame",
        instruction="Capture the whole plant in frame",
        inputs={
            "media": {
                "capture_the_whole_plant_in_frame": {
                    "image_b64": img,
                    "image_id": "whole_plant_photo",
                    "mime": "image/jpeg",
                }
            }
        },
    )

    obs = adapter.observe(req)

    assert obs.confidence == 0.0
    assert obs.summary == "Vision call failed: OpenAI returned no vision JSON content."
    assert "whole_plant_photo" in obs.evidence_refs


def test_capabilities_and_act():
    adapter = OpenAIVisionAdapter(api_key="sk-test", chat_fn=_fake_chat_fn)
    assert "observe" in adapter.capabilities()
    from core.adapters.base import ActionRequest

    res = adapter.act(ActionRequest(step_id="s1", action="noop"))
    assert res.ok is True
