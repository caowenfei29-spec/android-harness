"""Web server safety defaults (no phone required)."""
import json
import sys
import threading
from pathlib import Path
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import web  # noqa: E402
from android_harness.plan import TaskPlan  # noqa: E402


@pytest.fixture(autouse=True)
def clear_confirmation_challenges():
    web._CONFIRMATION_CHALLENGES.clear()
    yield
    web._CONFIRMATION_CHALLENGES.clear()


def test_python_console_is_disabled_by_default():
    web._UNSAFE_SCRIPT_ENABLED = False
    result = web._do_action("run", {"code": "raise Exception('executed')"})
    assert result["ok"] is False
    assert result["blocked"] is True


def test_web_binding_is_loopback_only():
    assert web._is_loopback("127.0.0.1") is True
    assert web._is_loopback("::1") is True
    assert web._is_loopback("localhost") is True
    assert web._is_loopback("0.0.0.0") is False
    assert web._is_loopback("192.168.1.10") is False


def test_server_refuses_non_loopback_even_with_unsafe():
    with pytest.raises(SystemExit, match="loopback"):
        web.main(["--host", "0.0.0.0", "--unsafe"])


def test_dns_rebinding_and_cross_origin_are_rejected():
    assert web._host_header_allowed("127.0.0.1:8741") is True
    assert web._host_header_allowed("localhost:8741") is True
    assert web._host_header_allowed("evil.example:8741") is False
    assert web._origin_allowed("http://127.0.0.1:8741") is True
    assert web._origin_allowed("https://evil.example") is False
    assert web._origin_allowed("null") is False
    assert web._origin_allowed(
        "http://127.0.0.1:9999", "127.0.0.1:8741") is False
    assert web._origin_allowed(
        "http://127.0.0.1:8741", "127.0.0.1:8741") is True


def test_web_tap_needs_confirmation_before_device_access():
    result = web._do_action("tap", {"x": 10, "y": 20})
    assert result["ok"] is False
    assert result["confirmation_required"] is True
    assert result["challenge"]
    assert result["plan_digest"]


def test_confirmed_boolean_cannot_bypass_or_invoke_llm(monkeypatch):
    generated = []
    monkeypatch.setattr(web, "llm_configured", lambda: True)
    monkeypatch.setattr(
        web, "generate_plan", lambda _prompt: generated.append(True))

    result = web._do_action(
        "natural", {"prompt": "发送消息", "confirmed": True})

    assert result["ok"] is False
    assert result["blocked"] is True
    assert "not authorization" in result["error"]
    assert generated == []


def test_direct_post_confirmed_true_cannot_bypass(monkeypatch):
    generated = []
    monkeypatch.setattr(web, "llm_configured", lambda: True)
    monkeypatch.setattr(
        web, "generate_plan", lambda _prompt: generated.append(True))
    server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({
            "op": "natural", "prompt": "发送消息", "confirmed": True,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/action",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result["ok"] is False
    assert result["blocked"] is True
    assert generated == []


def test_confirmation_executes_stored_plan_without_second_llm_call(monkeypatch):
    plan_a = TaskPlan.from_dict({"steps": [
        {"type": "tap", "target": "Plan A"}
    ]})
    plan_b = TaskPlan.from_dict({"steps": [
        {"type": "tap", "target": "Plan B"}
    ]})
    generated = []
    executed = []

    def generate(_prompt):
        generated.append(True)
        return plan_a if len(generated) == 1 else plan_b

    def execute(plan, _policy, _authorization):
        executed.append(plan)
        return {"ok": True, "plan": plan.to_dict()}

    monkeypatch.setattr(web, "llm_configured", lambda: True)
    monkeypatch.setattr(web, "generate_plan", generate)
    monkeypatch.setattr(web, "_execute_authorized_plan", execute)

    offered = web._do_action("natural", {"prompt": "ambiguous action"})
    assert offered["confirmation_required"] is True
    assert offered["plan_digest"] == plan_a.digest()
    assert len(generated) == 1

    confirmed = web._do_action("confirm", {
        "challenge": offered["challenge"],
        "plan_digest": offered["plan_digest"],
        # Client-supplied replacement plans are ignored. The server executes
        # the immutable plan stored with the challenge.
        "plan": plan_b.to_dict(),
    })
    assert confirmed["ok"] is True
    assert len(generated) == 1
    assert [plan.digest() for plan in executed] == [plan_a.digest()]

    replay = web._do_action("confirm", {
        "challenge": offered["challenge"],
        "plan_digest": offered["plan_digest"],
    })
    assert replay["ok"] is False
    assert replay["blocked"] is True
    assert len(executed) == 1


def test_confirmation_rejects_different_plan_digest(monkeypatch):
    plan_a = TaskPlan.from_dict({"steps": [
        {"type": "tap", "target": "Plan A"}
    ]})
    plan_b = TaskPlan.from_dict({"steps": [
        {"type": "tap", "target": "Plan B"}
    ]})
    executed = []
    monkeypatch.setattr(
        web, "_execute_authorized_plan",
        lambda plan, _policy, _authorization: executed.append(plan))

    offered = web._execute_plan(plan_a)
    rejected = web._do_action("confirm", {
        "challenge": offered["challenge"],
        "plan_digest": plan_b.digest(),
    })
    assert rejected["ok"] is False
    assert rejected["blocked"] is True
    assert "does not match" in rejected["error"]
    assert executed == []
