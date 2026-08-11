"""Regression coverage for actions that previously bypassed confirmation."""
import pytest

from android_harness.plan import TaskPlan
from android_harness.policy import AuthorizationError, PolicyEngine


@pytest.mark.parametrize("label", ["发送", "购买", "删除", "安装", "修改设置"])
def test_ambiguous_tap_labels_all_fail_without_confirmation(label):
    # The labels are deliberately not interpreted by policy. Every generic tap
    # is an ambiguous capability and therefore requires confirmation.
    plan = TaskPlan.from_dict({"steps": [{"type": "tap", "target": label}]})
    with pytest.raises(AuthorizationError):
        PolicyEngine().authorize(plan)


@pytest.mark.parametrize("step_type", ["send", "purchase", "delete", "install",
                                       "change_settings"])
def test_semantic_risky_steps_all_fail_without_confirmation(step_type):
    plan = TaskPlan.from_dict({"steps": [{"type": step_type, "target": "target"}]})
    with pytest.raises(AuthorizationError):
        PolicyEngine().authorize(plan)
