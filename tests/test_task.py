"""Tests for the task-level wrapper (no phone required).

These exercise the parts that are pure logic: step builders, the safety
planner's refusal of outward actions, and run_task's behaviour when the device
is absent (it must stop, not crash, and report a clear reason).
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


def test_run_task_halts_on_ask():
    # With a device present, the loop must STOP at the first step_ask.
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
    assert res["steps_run"] == 1  # tapped, then halted at ask
    assert calls == ["文件传输助手"]
    assert "确认发送" in res["reason"]
    assert res["stopped_at"] == steps[1]
