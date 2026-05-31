"""Tests for the deterministic SOP compiler fallback."""

from core.sop_compiler import compile_sop, suggest_output_schema

SOP = """# Demo SOP

## Capture
- Take a photo of the front bumper [vision] [evidence: front_photo] [produces: front]

## Tools
- Look up the order in the CRM [tool: crm_lookup]

## Decide
- Check status [tool: status_check] [decision: incident_active -> reply_a | reply_b]
- Reply a
- Reply b
- Send the resolution to the customer [review: customer_response]
"""


def test_modality_inference():
    wf = compile_sop(SOP)
    by_id = {s.id: s for s in wf.steps}
    assert by_id["take_a_photo_of_the_front_bumper"].modality == "vision"
    assert by_id["look_up_the_order_in_the_crm"].modality == "tool"
    assert by_id["look_up_the_order_in_the_crm"].tools_needed == ["crm_lookup"]


def test_review_point_inferred():
    wf = compile_sop(SOP)
    triggers = {p.trigger for p in wf.human_review_points}
    assert "customer_response" in triggers


def test_decision_targets_resolve_to_step_ids():
    wf = compile_sop(SOP)
    dp = wf.decision_points[0]
    step_ids = {s.id for s in wf.steps}
    assert dp.on_true in step_ids
    assert dp.on_false in step_ids


def test_deterministic():
    a = compile_sop(SOP).model_dump()
    b = compile_sop(SOP).model_dump()
    assert a == b


def test_suggest_schema_when_none():
    wf = compile_sop(SOP, output_schema=None)
    assert wf.output_schema["type"] == "object"
    assert "summary" in wf.output_schema["properties"]
    # Suggested directly from steps too.
    schema = suggest_output_schema(wf.steps, wf.goal)
    assert "completed" in schema["properties"]
