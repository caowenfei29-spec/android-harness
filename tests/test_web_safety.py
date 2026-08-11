"""Tests for the web safety whitelist (_safe_code).

These guard the natural-language path: an LLM translates a user's words into
harness code, and ONLY whitelisted read-only / navigation calls may run. Any
outward/destructive call or arbitrary Python must be rejected — even if phrased
in Chinese or via a disguised function name.
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from web import _safe_code


def test_allow_legit_navigation():
    code = (
        "from android_harness import helpers as H, task\n"
        "H.launch('抖音')\n"
        "H.scroll_screen(direction='up')\n"
        "print([n['text'] for n in H.dump_nodes()])\n"
    )
    ok, _ = _safe_code(code)
    assert ok is True


def test_block_disguised_send():
    ok, _ = _safe_code("H.send_message('你好')")
    assert ok is False


def test_block_os_import():
    ok, _ = _safe_code("import os\nos.system('rm -rf /')")
    assert ok is False


def test_block_non_harness_import():
    ok, _ = _safe_code("from requests import post\npost('http://evil')")
    assert ok is False


def test_block_bare_exec():
    ok, _ = _safe_code("exec('import os; os.system(\"x\")')")
    assert ok is False


def test_block_file_write():
    ok, _ = _safe_code("open('/tmp/x','w').write('y')")
    assert ok is False


def test_allow_send_wrapped_in_ask():
    # Outward action is allowed ONLY when wrapped in step_ask for the human.
    code = "task.run_task([task.step_tap('发送'), task.step_ask('确认发送?')])"
    ok, _ = _safe_code(code)
    assert ok is True
