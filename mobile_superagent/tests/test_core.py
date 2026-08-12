"""Unit tests for mobile_superagent core modules (no device required)."""
import os
import sys
import tempfile

# ensure package importable from repo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import router, schema, safety  # noqa: E402
from app.core import agent_loop  # noqa: E402
from app.core import verifier  # noqa: E402


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


# --- P1: send-rate throttle, messaging verifier, paste in whitelist --------

def test_schema_has_paste_action():
    assert "paste" in schema.ACTION_TYPES
    assert "set_clipboard" in schema.ACTION_TYPES


def test_send_rate_throttles_fast_repeat():
    g = safety.SafetyGuard(send_min_interval=3.0)
    # first send tap on a messaging page passes
    assert g.check("发消息", {"type": "tap", "x": 1, "y": 2},
                   page_text="发送") is None
    # immediate second send tap is blocked
    block = g.check("发消息", {"type": "tap", "x": 1, "y": 2},
                    page_text="发送")
    assert block is not None and "重复发送" in block


def test_verifier_confirms_sent_text_echo():
    v = verifier.MessagingVerifier()
    ok, note = v.verify_send("聊天记录: 你好呀\n刚才那条", "你好呀")
    assert ok
    assert "确认已发送" in note


def test_verifier_rejects_no_echo():
    v = verifier.MessagingVerifier()
    ok, _ = v.verify_send("聊天记录: 完全不同内容", "你好呀")
    assert not ok


def test_verifier_make_for_messaging_only():
    assert verifier.make_verifier("MESSAGING") is not None
    assert verifier.make_verifier("APP_INSTALL") is None


def test_target_package_extract():
    loop = agent_loop.AgentLoop.__new__(agent_loop.AgentLoop)
    loop.goal = "打开微信发消息"
    assert loop._target_package() == "com.tencent.mm"
    loop.goal = "随便"
    assert loop._target_package() is None


def test_alipay_install_not_blocked_as_payment():
    """'安装支付宝' must NOT trip the payment guard (支付宝 is an app name,
    not a payment action). Both page text with 翼支付 and the goal must pass."""
    g = safety.SafetyGuard()
    # goal contains 支付宝, page shows launcher with 翼支付 icon
    block = g.check("帮我安装支付宝",
                    {"type": "launch_app", "package_name": "com.eg.android.AlipayGphone"},
                    page_text="桌面 翼支付 微信 拨号")
    assert block is None


def test_real_payment_still_blocked():
    g = safety.SafetyGuard()
    block = g.check("帮我买这个", {"type": "tap", "x": 1, "y": 2},
                    page_text="确认支付 100元")
    assert block is not None
    assert "支付" in block


def test_store_detail_page_exempt_from_payment_guard():
    """Installing an app from a store detail page (which shows 支付/理财 marketing
    text) is NOT a payment action — must not be blocked."""
    g = safety.SafetyGuard()
    block = g.check(
        "帮我安装支付宝",
        {"type": "tap", "x": 1, "y": 2},
        page_text="支付宝 198.4亿次安装 174MB 生活缴费 支付 理财 贷款 [安装]")
    assert block is None


def test_real_payment_still_blocked_even_with_install_word():
    """A genuine payment page must still be blocked even if '安装' happens to
    appear — the payment guard only exempts INSTALL-intent goals."""
    g = safety.SafetyGuard()
    block = g.check(
        "帮我买这个",  # NOT an install goal
        {"type": "tap", "x": 1, "y": 2},
        page_text="确认支付 100元 [安装]")
    assert block is not None
    assert "支付" in block


# --- launch_app foreground verification (web 安装支付宝谎报 bug) -----------

def test_launch_requires_foreground_switch():
    """A launch_app whose command issued but foreground didn't switch must
    report failure with the real state, so the agent can't claim success."""
    import app.core.device_bridge as br
    class FakeDevice(br.AndroidDevice):
        def __init__(self):
            self.serial = "fake"
        def _pin(self): pass
        def is_installed(self, pkg): return True

    orig_launch = br.ADB.launch
    orig_current_app = br.AndroidDevice.current_app
    br.ADB.launch = lambda pkg: None
    br.AndroidDevice.current_app = lambda self: ("com.oppo.launcher", "Launcher")
    try:
        d = FakeDevice()
        r = d._launch({"package_name": "com.eg.android.AlipayGphone"})
        assert not r.ok  # foreground stayed on launcher -> must be failure
        assert "未切换" in r.message
        assert r.data["installed"] is True
    finally:
        br.ADB.launch = orig_launch
        br.AndroidDevice.current_app = orig_current_app


def test_launch_confirmed_when_foreground_switches():
    import app.core.device_bridge as br
    class FakeDevice(br.AndroidDevice):
        def __init__(self):
            self.serial = "fake"
        def _pin(self): pass
        def is_installed(self, pkg): return True

    orig_launch = br.ADB.launch
    orig_current_app = br.AndroidDevice.current_app
    br.ADB.launch = lambda pkg: None
    br.AndroidDevice.current_app = lambda self: ("com.eg.android.AlipayGphone", "X")
    try:
        d = FakeDevice()
        r = d._launch({"package_name": "com.eg.android.AlipayGphone"})
        assert r.ok
        assert "前台已确认" in r.message
    finally:
        br.ADB.launch = orig_launch
        br.AndroidDevice.current_app = orig_current_app


# --- input_text always clears + verifies (残留搜索词漂移 bug) --------------

def test_input_always_clears_and_verifies():
    """Typing must always clear the field first (stale search terms from a prior
    task must not masquerade as the new target) and re-read to verify."""
    import app.core.device_bridge as br
    calls = []

    class FakeDevice(br.AndroidDevice):
        def __init__(self):
            self.serial = "fake"
        def _pin(self): pass
        def _read_field_text(self): return "抖音"  # stale leftover that survived

    orig_tap, orig_clear, orig_unicode = br.ADB.tap, br.AndroidDevice._clear_field, \
        br.helpers.type_unicode if hasattr(br, "helpers") else None
    br.ADB.tap = lambda x, y: calls.append(("tap", x, y))
    br.AndroidDevice._clear_field = lambda self: calls.append(("clear",))
    import android_harness.helpers as H
    orig_type = H.type_unicode
    H.type_unicode = lambda t: calls.append(("type", t))
    try:
        d = FakeDevice()
        r = d._input_text({"x": 100, "y": 200, "text": "支付宝"})
        # clear called before type
        assert ("clear",) in calls
        assert ("type", "支付宝") in calls
        # field still shows stale text -> verification fails, no false success
        assert not r.ok
        assert "残留" in r.message
    finally:
        br.ADB.tap = orig_tap
        br.AndroidDevice._clear_field = orig_clear
        H.type_unicode = orig_type
