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
"""


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
