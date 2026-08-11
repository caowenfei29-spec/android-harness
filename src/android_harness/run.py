"""The android-harness CLI: exec Python from stdin with helpers pre-imported.
"""
import sys
from pathlib import Path

USAGE = """Usage:
  android-harness <<'PY'
  print(screen_info())
  PY

Commands:
  android-harness --doctor    diagnose adb + device + connection state
  android-harness skill       print the android-harness skill text
  android-harness task        run a JSON list of steps (read from stdin)
  android-harness web         start the local web control UI

Task steps (JSON array on stdin), each a dict with an "op":
  {"op":"open","app":"微信"}            open by launcher label or package
  {"op":"tap","text":"文件传输助手"}     tap a visible control by label
  {"op":"tap_id","res_id":"pkg:id/x"}   tap by resource-id
  {"op":"type","text":"hi"}             type ASCII into focused field
  {"op":"type_unicode","text":"中文"}    type via ADBKeyboard
  {"op":"wait","seconds":1.0}           pause
  {"op":"ask","prompt":"确认发送?"}      STOP and ask the human
Outward actions (send/post/buy/delete/install) must go through "ask".

Example:
  echo '[{"op":"open","app":"设置"},{"op":"tap","text":"关于手机"}]' | android-harness task
"""

_TASK_HELP = USAGE


def main():
    args = sys.argv[1:]
    if args and args[0] in {"-h", "--help"}:
        print(USAGE)
        return
    if args and args[0] in {"--doctor", "doctor"}:
        from .admin import run_doctor
        sys.exit(run_doctor())
    if args and args[0] == "skill":
        repo_root = Path(__file__).resolve().parent.parent.parent
        print((repo_root / "SKILL.md").read_text(encoding="utf-8"), end="")
        return
    if args and args[0] in {"task", "tasks"}:
        from . import task as _task_mod
        if len(args) > 1 and args[1] in {"-h", "--help", "help"}:
            print(_TASK_HELP)
            return
        # Expect a JSON list of step dicts on stdin; print the result.
        if sys.stdin.isatty():
            print(_TASK_HELP)
            return
        import json as _json
        try:
            steps = _json.loads(sys.stdin.read())
        except Exception as e:  # noqa: BLE001
            print(f"TASK ERROR: invalid JSON steps: {e}")
            return
        result = _task_mod.run_task(steps)
        print(_json.dumps(result, ensure_ascii=False))
        return
    if args and args[0] in {"web", "ui"}:
        repo_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(repo_root))
        import web as web_mod
        web_mod.main(args[1:])
        return
    if args or sys.stdin.isatty():
        sys.exit(USAGE)
    code = sys.stdin.read()
    if not code.strip():
        sys.exit(USAGE)
    from . import helpers
    g = {k: v for k, v in vars(helpers).items() if not k.startswith("_")}
    g["__name__"] = "__main__"
    exec(code, g)


if __name__ == "__main__":
    main()
