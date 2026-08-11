"""CLI regression tests for safe defaults and legacy JSON parsing."""
import io

import pytest

from android_harness import run


def test_no_args_prints_help_instead_of_executing_stdin(monkeypatch, capsys):
    monkeypatch.setattr(run.sys, "stdin", io.StringIO("raise Exception('boom')"))
    run.main([])
    assert "android-harness plan" in capsys.readouterr().out


def test_legacy_task_json_is_parsed_then_denied_by_policy(monkeypatch):
    monkeypatch.setattr(
        run.sys, "stdin", io.StringIO('[{"op":"tap","text":"发送"}]'))
    with pytest.raises(SystemExit, match="AUTHORIZATION DENIED"):
        run.main(["task"])
