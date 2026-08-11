"""Executor tests with a fake ADB helper surface."""
from android_harness.executor import Executor
from android_harness.plan import TaskPlan
from android_harness.policy import PolicyEngine


class FakeHelpers:
    def __init__(self):
        self.calls = []

    def home(self):
        self.calls.append(("home",))

    def tap_text(self, target, exact=False):
        self.calls.append(("tap", target, exact))

    def wait_stable(self):
        self.calls.append(("stable",))


def test_executor_runs_safe_json_only():
    plan = TaskPlan.from_dict({"steps": [{"type": "home"}]})
    policy = PolicyEngine()
    helpers = FakeHelpers()
    result = Executor(policy=policy, helpers=helpers).execute(
        plan, policy.authorize(plan))
    assert result.done is True
    assert helpers.calls == [("home",), ("stable",)]


def test_executor_rejects_authorization_for_another_plan():
    policy = PolicyEngine()
    safe = TaskPlan.from_dict({"steps": [{"type": "home"}]})
    risky = TaskPlan.from_dict({"steps": [{"type": "tap", "target": "发送"}]})
    helpers = FakeHelpers()
    result = Executor(policy=policy, helpers=helpers).execute(
        risky, policy.authorize(safe))
    assert result.done is False
    assert helpers.calls == []
    assert "authorization does not match" in result.reason
