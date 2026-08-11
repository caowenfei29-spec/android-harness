"""Web server safety defaults (no phone required)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import web  # noqa: E402


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
