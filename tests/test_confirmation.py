"""Confirmation token integrity and sequencing tests."""
import pytest

from android_harness.plan import TaskPlan
from android_harness.policy import AuthorizationError, PolicyEngine


def test_ask_is_prompt_not_authorization():
    plan = TaskPlan.from_dict({"steps": [
        {"type": "ask", "prompt": "确认发送?"},
        {"type": "tap", "target": "发送"},
    ]})
    with pytest.raises(AuthorizationError):
        PolicyEngine().authorize(plan)


def test_human_confirmation_mints_token_for_following_step():
    prompts = []
    plan = TaskPlan.from_dict({"steps": [
        {"type": "ask", "prompt": "确认发送?"},
        {"type": "tap", "target": "发送"},
    ]})
    policy = PolicyEngine(secret=b"fixed-secret-for-tests-32-bytes!")
    auth = policy.authorize(
        plan, confirmer=lambda request: prompts.append(request.prompt) or True)
    assert prompts == ["确认发送?"]
    assert len(auth.tokens) == 1
    policy.assert_authorized(plan, plan.steps[1], auth)


def test_token_cannot_be_replayed_for_changed_plan():
    policy = PolicyEngine(secret=b"fixed-secret-for-tests-32-bytes!")
    original = TaskPlan.from_dict({"steps": [{"type": "tap", "target": "发送"}]})
    auth = policy.authorize(original, confirmer=lambda _request: True)
    changed = TaskPlan.from_dict({"steps": [{"type": "tap", "target": "删除"}]})
    with pytest.raises(AuthorizationError, match="does not match"):
        policy.assert_authorized(changed, changed.steps[0], auth)
