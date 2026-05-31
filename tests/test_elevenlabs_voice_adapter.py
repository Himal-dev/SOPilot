"""ElevenLabsVoiceAdapter transcribes (observe) and synthesizes (act)."""

from core.adapters.base import ActionRequest, ObserveRequest
from core.kids_voice_assessment.providers import MockVoiceProvider
from core.voice_adapter import ElevenLabsVoiceAdapter


def test_observe_transcribes_via_provider():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    req = ObserveRequest(
        step_id="ask_the_gardener",
        instruction="Ask about light and watering",
        inputs={
            "media": {
                "ask_the_gardener": {
                    "audio_path": "/tmp/answer.wav",
                    "recording_id": "rec1",
                    "options": {
                        "mock_transcript": "I water it every day in low light"
                    },
                }
            }
        },
    )
    obs = adapter.observe(req)
    assert obs.source == "voice"
    assert obs.model.startswith("elevenlabs") or obs.model == "mock"
    assert "water" in obs.content["transcript"].lower()
    assert obs.confidence > 0.0
    assert "rec1" in obs.evidence_refs


def test_observe_without_audio_returns_low_confidence():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    req = ObserveRequest(step_id="s1", instruction="ask", inputs={"media": {}})
    obs = adapter.observe(req)
    assert obs.confidence == 0.0
    assert "no audio" in obs.summary.lower()


def test_observe_accepts_agent_transcript_without_retranscribing():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    req = ObserveRequest(
        step_id="ask_the_gardener",
        instruction="Ask about light and watering",
        inputs={
            "media": {
                "ask_the_gardener": {
                    "transcript": "I water weekly in bright indirect light",
                    "recording_id": "agent-turn-1",
                    "content": {"watering": "weekly", "light": "bright indirect"},
                    "model": "elevenlabs-agent",
                }
            }
        },
    )
    obs = adapter.observe(req)
    assert obs.summary == "I water weekly in bright indirect light"
    assert obs.content["watering"] == "weekly"
    assert obs.model == "elevenlabs-agent"
    assert obs.evidence_refs == ["agent-turn-1"]


def test_act_synthesizes_speech():
    adapter = ElevenLabsVoiceAdapter(provider=MockVoiceProvider())
    res = adapter.act(
        ActionRequest(
            step_id="s1",
            action="speak",
            payload={"text": "Here is your care plan."},
        )
    )
    assert res.ok is True
    assert res.data.get("audio_uri")
