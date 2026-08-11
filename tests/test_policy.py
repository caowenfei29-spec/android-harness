"""Capability-based policy classification tests."""
import pytest

from android_harness.plan import TaskPlan
from android_harness.policy import AuthorizationError, PolicyEngine, RiskLevel


def _step(step):
    return TaskPlan.from_dict({"steps": [step]}).steps[0]


def test_policy_classifies_capabilities_not_labels():
    policy = PolicyEngine(secret=b"test" * 8)
    assert policy.risk_classify(_step({"type": "home"})) == RiskLevel.SAFE_NAVIGATION
    assert policy.risk_classify(_step({"type": "read_ui"})) == RiskLevel.SAFE_READ
    assert policy.risk_classify(
        _step({"type": "tap", "target": "harmless-looking label"})
    ) == RiskLevel.USER_CONFIRM_REQUIRED
    assert policy.risk_classify(
        _step({"type": "delete", "target": "item"})
    ) == RiskLevel.DESTRUCTIVE


def test_safe_plan_authorizes_without_tokens():
    plan = TaskPlan.from_dict({"steps": [
        {"type": "home"}, {"type": "read_ui"}, {"type": "back"}
    ]})
    auth = PolicyEngine().authorize(plan)
    assert auth.tokens == ()


def test_risky_plan_fails_closed_without_confirmation():
    plan = TaskPlan.from_dict({"steps": [{"type": "tap", "target": "anything"}]})
    with pytest.raises(AuthorizationError, match="requires human confirmation"):
        PolicyEngine().authorize(plan)
