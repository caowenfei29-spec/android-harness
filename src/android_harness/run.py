"""Command line interface for planning and policy-gated execution."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .executor import Executor
from .plan import PlanValidationError, TaskPlan
from .policy import AuthorizationError, ConfirmationRequest, PolicyEngine


USAGE = """Usage:
  android-harness plan "Open 微信"             output a JSON Task Plan
  android-harness execute plan.json --confirm validate, confirm, and execute
  android-harness execute -                   execute JSON from stdin (safe steps only)

Compatibility and administration:
  android-harness task                        alias for execute -
  android-harness --unsafe-script [file|-]    UNSAFE: execute trusted Python
  android-harness --doctor                    diagnose adb and device state
  android-harness skill                       print SKILL.md
  android-harness web [--unsafe]              local web UI; Python disabled by default

Risk is classified by capability, not button text. Generic tap and input
steps require confirmation. Destructive and settings steps are explicitly
classified DESTRUCTIVE. Piped/non-interactive execution cannot confirm.
"""


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(USAGE)
        return
    command = args.pop(0)
    if command in {"--doctor", "doctor"}:
        from .admin import run_doctor
        raise SystemExit(run_doctor())
    if command == "skill":
        repo_root = Path(__file__).resolve().parent.parent.parent
        print((repo_root / "SKILL.md").read_text(encoding="utf-8"), end="")
        return
    if command == "plan":
        _plan_command(args)
        return
    if command in {"execute", "task", "tasks"}:
        if command in {"task", "tasks"} and not args:
            args = ["-"]
        _execute_command(args, legacy=command in {"task", "tasks"})
        return
    if command == "--unsafe-script":
        _unsafe_script(args)
        return
    if command in {"web", "ui"}:
        repo_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(repo_root))
        import web as web_module
        web_module.main(args)
        return
    raise SystemExit("Unknown command.\n\n" + USAGE)


def _plan_command(args: list[str]) -> None:
    goal = " ".join(args).strip()
    if not goal and not sys.stdin.isatty():
        goal = sys.stdin.read().strip()
    if not goal:
        raise SystemExit("plan requires a natural-language goal")
    from .llm import configured, generate_plan
    from .task import plan_from_goal

    legacy = plan_from_goal(goal)
    if legacy is not None:
        from .plan import normalize_legacy_steps
        plan = normalize_legacy_steps(legacy)
    elif configured():
        plan = generate_plan(goal)
    else:
        raise SystemExit(
            "No deterministic plan is available for this goal and the LLM is "
            "not configured. Set LLM_* in .env or supply Task Plan JSON directly.")
    print(plan.to_json())


def _execute_command(args: list[str], *, legacy: bool = False) -> None:
    confirm = False
    paths: list[str] = []
    for arg in args:
        if arg == "--confirm":
            confirm = True
        elif arg in {"-h", "--help", "help"}:
            print(USAGE)
            return
        else:
            paths.append(arg)
    if len(paths) > 1:
        raise SystemExit("execute accepts at most one plan path")
    source = paths[0] if paths else "-"
    if source == "-":
        if sys.stdin.isatty():
            raise SystemExit("execute needs a JSON file or JSON on stdin")
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")
    try:
        if legacy:
            from .plan import normalize_legacy_steps
            value = json.loads(raw)
            plan = (normalize_legacy_steps(value) if isinstance(value, list)
                    and any(isinstance(step, dict) and "op" in step
                            for step in value)
                    else TaskPlan.from_dict(value))
        else:
            plan = TaskPlan.from_json(raw)
    except (PlanValidationError, json.JSONDecodeError) as exc:
        raise SystemExit(f"PLAN ERROR: {exc}") from exc

    policy = PolicyEngine()
    confirmer = _interactive_confirm if confirm else None
    if confirm and source == "-":
        raise SystemExit(
            "Interactive confirmation requires a plan file; stdin is occupied "
            "by JSON. Save the plan, then run execute FILE --confirm.")
    try:
        authorization = policy.authorize(plan, confirmer=confirmer)
    except AuthorizationError as exc:
        raise SystemExit(f"AUTHORIZATION DENIED: {exc}") from exc

    from . import helpers
    try:
        helpers.ensure_device()
        result = Executor(policy=policy, helpers=helpers).execute(
            plan, authorization).to_dict()
    except Exception as exc:  # noqa: BLE001
        result = {"done": False, "steps_run": 0, "stopped_at": None,
                  "reason": f"{type(exc).__name__}: {exc}", "outputs": []}
    print(json.dumps(result, ensure_ascii=False))
    if not result["done"]:
        raise SystemExit(1)


def _interactive_confirm(request: ConfirmationRequest) -> bool:
    print("\nHUMAN CONFIRMATION REQUIRED", file=sys.stderr)
    print(f"Risk: {request.risk.value}", file=sys.stderr)
    print(f"Step: {json.dumps(request.step.to_dict(), ensure_ascii=False)}",
          file=sys.stderr)
    print(f"Prompt: {request.prompt}", file=sys.stderr)
    answer = input("Type 'yes' to authorize this exact step: ")
    return answer.strip().lower() == "yes"


def _unsafe_script(args: list[str]) -> None:
    if len(args) > 1:
        raise SystemExit("--unsafe-script accepts at most one file path")
    source = args[0] if args else "-"
    if source == "-":
        if sys.stdin.isatty():
            raise SystemExit("--unsafe-script needs a file or Python on stdin")
        code = sys.stdin.read()
    else:
        code = Path(source).read_text(encoding="utf-8")
    print(
        "WARNING: --unsafe-script executes unrestricted Python on this host "
        "and bypasses the JSON policy engine.", file=sys.stderr)
    from . import helpers
    helpers.enable_unsafe_agent_helpers()
    namespace: dict[str, Any] = {
        key: value for key, value in vars(helpers).items()
        if not key.startswith("_")
    }
    namespace["__name__"] = "__main__"
    exec(compile(code, source, "exec"), namespace)


if __name__ == "__main__":
    main()
