"""Unit tests for mobile_superagent core modules (no device required)."""
import os
import sys
import tempfile

# ensure package importable from repo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import router, schema, safety  # noqa: E402
from app.core import agent_loop  # noqa: E402


def test_extract_json_plain():
    assert schema.extract_json('{"a":1}') == {"a": 1}


def test_extract_json_with_fence():
    d = schema.extract_json('```json\n{"a":1}\n```')
    assert d == {"a": 1}


def test_extract_json_prose_wrapped():
    d = schema.extract_json('prefix {"type":"tap","x":1,"y":2} suffix')
    assert d == {"type": "tap", "x": 1, "y": 2}


def test_parse_agent_output_valid():
    out, action = schema.parse_agent_output({
        "observe": "o", "plan": "p", "action": {"type": "tap", "x": 1, "y": 2},
        "status": "running",
    })
    assert action["type"] == "tap"
    assert out.status == "running"
    assert out.observe == "o"


def test_parse_agent_output_rejects_unknown_action():
    try:
        schema.parse_agent_output({"action": {"type": "rm_rf"}})
        assert False, "should have raised"
    except ValueError:
        pass


def test_route_skill_install():
    assert router.route_skill("安装 YouTube") == "APP_INSTALL"


def test_route_skill_feed():
    assert router.route_skill("打开抖音浏览5个视频") == "FEED_SUMMARY"


def test_route_skill_hint_overrides():
    assert router.route_skill("随便", skill_hint="BROWSER") == "BROWSER"


def test_safety_blocks_uninstall_without_intent():
    g = safety.SafetyGuard()
    block = g.check("打开微信", {"type": "uninstall_app",
                                "package_name": "com.tencent.mm"})
    assert block is not None


def test_safety_passes_uninstall_with_intent():
    g = safety.SafetyGuard()
    block = g.check("卸载微信", {"type": "uninstall_app",
                                "package_name": "com.tencent.mm"})
    assert block is None


def test_safety_blocks_password_input():
    g = safety.SafetyGuard()
    block = g.check("登录", {"type": "input_text", "text": "mypassword123"},
                    page_text="请输入密码")
    assert block is not None


def test_safety_blocks_payment():
    g = safety.SafetyGuard()
    block = g.check("买东西", {"type": "tap", "x": 1, "y": 2},
                    page_text="立即支付")
    assert block is not None


def test_safety_allows_auto_pay_when_enabled():
    g = safety.SafetyGuard(allow_auto_pay=True)
    block = g.check("买东西", {"type": "tap", "x": 1, "y": 2},
                    page_text="立即支付")
    assert block is None


# --- serial isolation (adb.set_serial uses contextvars, not a global) -------

def test_adb_serial_is_contextvar_not_global():
    import threading
    from android_harness import adb
    assert not hasattr(adb, "SERIAL"), "global SERIAL must be removed"

    # Two concurrent threads must not leak serial to each other.
    seen = {}

    def worker(name, serial):
        adb.set_serial(serial)
        time.sleep(0.05)  # let the other thread run
        seen[name] = adb._current_serial()

    import time
    a = threading.Thread(target=worker, args=("a", "dev_A:5555"))
    b = threading.Thread(target=worker, args=("b", "dev_B:5555"))
    a.start(); b.start(); a.join(); b.join()
    assert seen["a"] == "dev_A:5555"
    assert seen["b"] == "dev_B:5555"


def test_agent_ocr_gated_by_skill():
    # feed-like skills use OCR; install-type skills don't.
    assert "FEED_SUMMARY" in agent_loop._OCR_SKILLS
    assert "APP_INSTALL" not in agent_loop._OCR_SKILLS


def test_app_aliases_cover_core_apps():
    assert agent_loop.APP_ALIASES["抖音"] == "com.ss.android.ugc.aweme"
    assert agent_loop.APP_ALIASES["微信"] == "com.tencent.mm"
