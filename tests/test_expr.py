"""Tests for the safe expression evaluator."""

import pytest

from core.planner.expr import ExprError, safe_eval


def test_empty_is_true():
    assert safe_eval("", {}) is True


def test_comparison_and_names():
    assert safe_eval("tread_depth_mm >= 2", {"tread_depth_mm": 3}) is True
    assert safe_eval("tread_depth_mm >= 2", {"tread_depth_mm": 1.5}) is False


def test_boolean_and_membership():
    ctx = {"incident_active": True, "code": "DECLINED", "codes": ["DECLINED", "OK"]}
    assert safe_eval("incident_active and code in codes", ctx) is True
    assert safe_eval("not incident_active", ctx) is False


def test_missing_name_is_none_not_error():
    # Unknown names resolve to None so authors can write tolerant rules.
    assert safe_eval("missing == None", {}) is True


def test_unsupported_syntax_rejected():
    with pytest.raises(ExprError):
        safe_eval("__import__('os')", {})
