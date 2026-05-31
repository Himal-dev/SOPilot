"""Run the BoloBuddy local fixture battery demo."""

from __future__ import annotations

import json
from pathlib import Path

from core.kids_voice_assessment.providers import MockVoiceProvider
from core.kids_voice_assessment.service import KidsVoiceAssessmentService


def main() -> None:
    example_dir = Path(__file__).resolve().parent
    service = KidsVoiceAssessmentService(
        example_dir=example_dir,
        provider=MockVoiceProvider(),
    )
    service.config["runtime"]["allow_fixture_provider_for_local_demo"] = True
    session = service.create_session(
        child_id="demo_child",
        age_years=7,
        consent_status="verified",
        viewer_role="child",
    )
    service.attach_audio(
        session.session_id,
        raw_audio_uri="mock://audio/red_ball_skip_article",
        duration_ms=3400,
        volume_score=0.84,
        noise_score=0.82,
        vad_speech_detected=True,
    )
    service.run_battery_session(
        session.session_id,
        task_inputs={
            "age7_8_code_switch_lunch": {
                "mock_transcript": "I went school phir lunch khaya"
            },
            "age7_8_story_sequence_space": {
                "mock_transcript": "pehle rocket moon gaya phir robot happy hua"
            },
            "age7_8_memory_metro": {
                "mock_transcript": "the metro stopped then my dost found blue ticket"
            },
        },
    )
    print("Child result")
    print(json.dumps(service.get_result(session.session_id, viewer_role="child"), indent=2))
    print("\nParent report")
    print(json.dumps(service.get_result(session.session_id, viewer_role="parent"), indent=2))


if __name__ == "__main__":
    main()
