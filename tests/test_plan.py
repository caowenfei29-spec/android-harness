"""Strict JSON Task Plan parser tests."""
import json

import pytest

from android_harness.plan import PlanValidationError, TaskPlan


def test_json_plan_round_trip_and_ids():
    plan = TaskPlan.from_json(json.dumps({
        "steps": [{"type": "open_app", "target": "微信"},
                  {"type": "read_ui"}]
    }))
    assert [step.id for step in plan.steps] == ["step-1", "step-2"]
    assert TaskPlan.from_json(plan.to_json()).digest() == plan.digest()


@pytest.mark.parametrize("payload", [
    {"steps": [{"type": "python", "code": "print(1)"}]},
    {"steps": [{"type": "tap", "target": "x", "code": "print(1)"}]},
    {"steps": [{"type": "wait", "seconds": float("inf")}]},
    {"steps": [{"type": "swipe", "direction": "sideways"}]},
    {"steps": [{"type": "read_ui", "unexpected": True}]},
])
def test_parser_rejects_non_schema_input(payload):
    with pytest.raises(PlanValidationError):
        TaskPlan.from_dict(payload)


def test_parser_rejects_duplicate_explicit_ids():
    with pytest.raises(PlanValidationError, match="duplicate"):
        TaskPlan.from_dict({"steps": [
            {"id": "same", "type": "home"},
            {"id": "same", "type": "back"},
        ]})
