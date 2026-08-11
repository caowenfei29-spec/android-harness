"""Tests for the task-level wrapper (no phone required).

These exercise compatibility builders and the policy-backed run_task wrapper.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from android_harness import task  # noqa: E402


def test_step_builders_shape():
    assert task.step_open("微信") == {"op": "open", "app": "微信"}
    assert task.step_tap("确定") == {"op": "tap", "text": "确定", "exact": False}
    assert task.step_tap("确定", exact=True)["exact"] is True
    assert task.step_tap_id("com.x:id/y") == {"op": "tap_id", "res_id": "com.x:id/y"}
    assert task.step_type("hi") == {"op": "type", "text": "hi"}
    assert task.step_type_unicode("中文") == {"op": "type_unicode", "text": "中文"}
    assert task.step_wait(2.0) == {"op": "wait", "seconds": 2.0}
    assert task.step_ask("确认?") == {"op": "ask", "prompt": "确认?"}


def test_plan_from_goal_open():
    plan = task.plan_from_goal("Open 微信")
    assert plan == [{"op": "open", "app": "微信"}]


def test_plan_from_goal_refuses_outward():
    # Outward/hard-to-reverse actions must NOT be auto-planned.
    assert task.plan_from_goal("Send a message") is None
    assert task.plan_from_goal("Delete the photo") is None
    assert task.plan_from_goal("Buy this") is None


def test_plan_from_goal_unknown_is_none():
    assert task.plan_from_goal("do something vague") is None


def test_run_task_stops_when_no_device():
    # Simulate no phone connected: H.ensure_device raises.
    class FakeH:
        @staticmethod
        def ensure_device():
            raise RuntimeError("No Android phone is connected via ADB.")

        @staticmethod
        def wait_stable():
            return True

    steps = [task.step_open("设置"), task.step_tap("关于手机")]
    res = task.run_task(steps, helpers=FakeH)
    assert res["done"] is False
    assert res["steps_run"] == 0
    assert "No Android phone" in res["reason"]
    assert res["stopped_at"] == steps[0]


def test_run_task_blocks_risky_step_before_late_ask():
    # A later ask cannot retroactively authorize an earlier risky tap.
    calls = []

    class FakeH:
        @staticmethod
        def ensure_device():
            pass

        @staticmethod
        def tap_text(text, exact=False):
            calls.append(text)

        @staticmethod
        def wait_stable():
            return True

    steps = [
        task.step_tap("文件传输助手"),
        task.step_ask("确认发送这条消息?"),
        task.step_tap("发送"),
    ]
    res = task.run_task(steps, helpers=FakeH)
    assert res["done"] is False
    assert res["steps_run"] == 0
    assert calls == []
    assert "requires human confirmation" in res["reason"]


def test_run_task_ask_then_confirm_then_tap():
    calls = []

    class FakeH:
        @staticmethod
        def ensure_device():
            pass

        @staticmethod
        def tap_text(text, exact=False):
            calls.append(text)

        @staticmethod
        def wait_stable():
            return True

    prompts = []
    steps = [task.step_ask("确认发送?"), task.step_tap("发送")]
    res = task.run_task(
        steps, helpers=FakeH,
        confirmer=lambda request: prompts.append(request.prompt) or True)
    assert res["done"] is True
    assert calls == ["发送"]
    assert prompts == ["确认发送?"]
