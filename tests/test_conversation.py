"""Guided conversation tool contracts generated from an agent manifest."""

from pathlib import Path

from sopilot.conversation import (
    RecordTopic,
    build_client_tool_configs,
    build_client_tool_summary,
    build_guided_instructions,
    build_guided_tool_names,
    build_retry_policy,
    infer_record_topics,
)
from sopilot.scaffold import build_agent_manifest

AGENT = Path(__file__).resolve().parents[1] / "examples" / "plant_doctor_agent"


TOPICS = [
    RecordTopic(key="watering", label="watering routine"),
    RecordTopic(key="light_location", label="light and location"),
    RecordTopic(key="drainage_soil", label="pot drainage and soil condition"),
    RecordTopic(key="recent_changes_pests", label="recent changes or pests"),
]


def test_guided_tool_contract_can_keep_product_specific_names():
    manifest = build_agent_manifest(AGENT)
    names = build_guided_tool_names(
        manifest,
        state_tool="getPlantDoctorState",
        submit_tool="submitPlantDoctorRun",
        record_answer_tool="recordCareHabitAnswer",
        capture_tool_overrides={
            "whole_plant_photo": "captureWholePlantPhoto",
            "closeup_photo": "captureCloseupPhoto",
        },
    )

    summary = build_client_tool_summary(manifest, names)
    assert set(summary) == {
        "getPlantDoctorState",
        "captureWholePlantPhoto",
        "captureCloseupPhoto",
        "recordCareHabitAnswer",
        "submitPlantDoctorRun",
    }

    configs = build_client_tool_configs(manifest, names, record_topics=TOPICS)
    record = next(tool for tool in configs if tool["name"] == "recordCareHabitAnswer")
    assert record["parameters"]["required"] == ["topic", "answer"]
    assert record["parameters"]["properties"]["topic"]["enum"] == [
        "watering",
        "light_location",
        "drainage_soil",
        "recent_changes_pests",
    ]
    submit = next(tool for tool in configs if tool["name"] == "submitPlantDoctorRun")
    assert submit["parameters"]["required"] == ["care_habits_transcript"]


def test_guided_instructions_include_manifest_questions_and_tool_names():
    manifest = build_agent_manifest(AGENT)
    names = build_guided_tool_names(
        manifest,
        state_tool="getPlantDoctorState",
        submit_tool="submitPlantDoctorRun",
        record_answer_tool="recordCareHabitAnswer",
        capture_tool_overrides={
            "whole_plant_photo": "captureWholePlantPhoto",
            "closeup_photo": "captureCloseupPhoto",
        },
    )

    instructions = build_guided_instructions(
        manifest,
        names,
        record_topics=TOPICS,
        final_policy="After the final message, stop asking questions.",
    )
    assert "captureWholePlantPhoto" in instructions
    assert "captureCloseupPhoto" in instructions
    assert "recordCareHabitAnswer" in instructions
    assert "submitPlantDoctorRun" in instructions
    assert "What is your watering routine?" in instructions
    assert "Any recent changes" in instructions
    assert "After the final message" in instructions
    assert "retry_photo_fields" in instructions
    assert "Do not re-ask interview answers" in instructions


def test_guided_contract_infers_record_topics_from_manifest_questions():
    manifest = build_agent_manifest(AGENT)
    names = build_guided_tool_names(manifest)

    topics = infer_record_topics(manifest)
    assert [topic.key for topic in topics] == [
        "watering_routine",
        "light_location_plant",
        "pot_have_drainage_soil",
        "any_recent_changes_signs_of_pests",
    ]

    configs = build_client_tool_configs(manifest, names)
    record = next(tool for tool in configs if tool["name"] == "recordInterviewAnswer")
    assert record["parameters"]["properties"]["topic"]["enum"] == [
        "watering_routine",
        "light_location_plant",
        "pot_have_drainage_soil",
        "any_recent_changes_signs_of_pests",
    ]


def test_retry_policy_maps_media_fields_to_capture_tools():
    manifest = build_agent_manifest(AGENT)
    names = build_guided_tool_names(
        manifest,
        capture_tool_overrides={
            "whole_plant_photo": "captureWholePlantPhoto",
            "closeup_photo": "captureCloseupPhoto",
        },
    )

    policy = build_retry_policy(manifest, names)
    assert "whole_plant_photo -> captureWholePlantPhoto" in policy
    assert "closeup_photo -> captureCloseupPhoto" in policy
    assert "preserve all successful captures and answers" in policy
