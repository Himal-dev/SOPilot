"""Manifest-driven media normalization for app surfaces."""

from pathlib import Path

from sopilot.media import MediaAsset, build_media_map, missing_required_media
from sopilot.scaffold import build_agent_manifest

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


def test_build_media_map_keys_assets_by_step_id():
    manifest = build_agent_manifest(AGENT)
    media = build_media_map(
        manifest,
        {
            "whole_plant_photo": MediaAsset.from_bytes(
                "whole_plant_photo", b"whole", mime="image/jpeg", filename="whole.jpg"
            ),
            "closeup_photo": MediaAsset.from_bytes(
                "closeup_photo", b"close", mime="image/png", filename="close.png"
            ),
            "care_habits_audio": MediaAsset.from_transcript(
                "care_habits_audio",
                "watering weekly; bright indirect light; drainage holes",
                content={"watering": "weekly"},
                model="voice-agent",
            ),
        },
    )

    assert media["capture_the_whole_plant_in_frame"]["image_id"] == "whole_plant_photo"
    assert media["capture_the_whole_plant_in_frame"]["mime"] == "image/jpeg"
    assert media["capture_a_close_up_of_the_affected_leaves_or_ste"]["mime"] == "image/png"
    voice = media["ask_the_gardener_about_care_habits_and_recent_ch"]
    assert voice["transcript"].startswith("watering weekly")
    assert voice["content"]["watering"] == "weekly"
    assert missing_required_media(manifest, media) == []


def test_audio_bytes_are_written_to_temp_path(tmp_path):
    manifest = build_agent_manifest(AGENT)
    media = build_media_map(
        manifest,
        {
            "care_habits_audio": MediaAsset.from_bytes(
                "care_habits_audio", b"audio", mime="audio/webm", filename="answer.webm"
            )
        },
        temp_dir=tmp_path,
        filename_prefix="test_agent",
    )

    audio_path = Path(media["ask_the_gardener_about_care_habits_and_recent_ch"]["audio_path"])
    assert audio_path.exists()
    assert audio_path.suffix == ".webm"
    assert audio_path.read_bytes() == b"audio"


def test_missing_required_media_reports_uncollected_steps():
    manifest = build_agent_manifest(AGENT)
    media = build_media_map(
        manifest,
        {
            "whole_plant_photo": MediaAsset.from_bytes(
                "whole_plant_photo", b"whole", mime="image/jpeg"
            )
        },
    )

    missing = missing_required_media(manifest, media)
    assert [item.evidence_refs for item in missing] == [
        ["closeup_photo"],
        ["care_habits_audio"],
    ]
