"""Reusable JSON report writer prompt and OpenAI client helpers."""

import json

import pytest

from sopilot.report_writer import (
    ReportPromptSpec,
    ReportWriterError,
    build_openai_json_report_request,
    build_report_prompt_payload,
    parse_openai_json_report_response,
    write_openai_json_report,
)


def _spec():
    return ReportPromptSpec(
        name="trial_report",
        expert_role="You are a careful domain expert.",
        task="Explain the likely issue and next action.",
        output_contract='{"summary": string, "actions": [string]}',
        style_rules=["Be specific.", "Do not invent evidence."],
        model_env="OPENAI_TRIAL_REPORT_MODEL",
        default_model="gpt-test",
        max_tokens=321,
    )


def test_build_report_prompt_payload_keeps_fields_instruction_and_context():
    payload = build_report_prompt_payload(
        {"symptoms": {"value": "yellow leaves"}},
        instruction="Use the latest care context.",
        context={"locale": "trial"},
    )

    assert payload["symptoms"]["value"] == "yellow leaves"
    assert payload["instruction"] == "Use the latest care context."
    assert payload["context"] == {"locale": "trial"}


def test_build_openai_json_report_request_is_evidence_bound():
    payload = {"symptoms": {"value": "yellow leaves"}}
    request = build_openai_json_report_request(payload, _spec(), model="gpt-live")

    system = request["messages"][0]["content"]
    assert request["model"] == "gpt-live"
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 321
    assert "careful domain expert" in system
    assert "Use only the provided evidence fields" in system
    assert '{"summary": string' in system
    assert json.loads(request["messages"][1]["content"]) == payload


def test_write_openai_json_report_returns_none_without_key():
    result = write_openai_json_report({"field": "value"}, _spec(), env={})
    assert result is None


def test_write_openai_json_report_posts_and_parses_json():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"summary": "Specific report."})
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def opener(req, timeout):
        captured["timeout"] = timeout
        captured["auth"] = req.headers["Authorization"]
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return Response()

    result = write_openai_json_report(
        {"field": "value"},
        _spec(),
        env={"OPENAI_API_KEY": "test-key", "OPENAI_TRIAL_REPORT_MODEL": "gpt-env"},
        opener=opener,
    )

    assert result == {"summary": "Specific report.", "model": "gpt-env"}
    assert captured["timeout"] == 60
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == "gpt-env"


def test_parse_openai_json_report_response_rejects_bad_json():
    with pytest.raises(ReportWriterError):
        parse_openai_json_report_response(
            {"choices": [{"message": {"content": "not json"}}]}
        )
