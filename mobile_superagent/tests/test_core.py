"""Unit tests for mobile_superagent core modules (no device required)."""
import os
import sys
import tempfile

# ensure package importable from repo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import router, schema, safety  # noqa: E402


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
