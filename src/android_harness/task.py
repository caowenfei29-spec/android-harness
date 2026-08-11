"""Compatibility task API backed by the policy-driven JSON executor.

The historical step builders keep their dictionary shapes.  ``run_task`` now
normalizes those dictionaries into a strict TaskPlan and cannot execute a
risky step unless PolicyEngine has issued a confirmation token for it.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from .executor import Executor
from .plan import PlanValidationError, TaskPlan, normalize_legacy_steps
from .policy import AuthorizationError, ConfirmationRequest, PolicyEngine


Step = dict[str, Any]


def step_open(app: str) -> Step:
    return {"op": "open", "app": app}


def step_tap(text: str, exact: bool = False) -> Step:
    return {"op": "tap", "text": text, "exact": exact}


def step_tap_id(res_id: str) -> Step:
    return {"op": "tap_id", "res_id": res_id}


def step_type(text: str) -> Step:
    return {"op": "type", "text": text}


def step_type_unicode(text: str) -> Step:
    return {"op": "type_unicode", "text": text}


def step_wait(seconds: float = 1.0) -> Step:
    return {"op": "wait", "seconds": seconds}


def step_ask(prompt: str) -> Step:
    """Attach a human-facing prompt to the next risky step."""
    return {"op": "ask", "prompt": prompt}


def run_task(
    steps: Sequence[Step] | TaskPlan,
    *,
    on_step: Callable[[dict[str, Any], int], None] | None = None,
    max_steps: int = 50,
    helpers: Any = None,
    confirmer: Callable[[ConfirmationRequest], bool] | None = None,
) -> dict[str, Any]:
    """Execute legacy task steps through PolicyEngine and Executor.

    Without ``confirmer``, every tap, resource tap, text input, outward action,
    destructive action, or settings change fails before ADB is invoked.  A
    preceding ``step_ask`` supplies the prompt but is not itself authorization.
    """
    from . import helpers as real_helpers

    H = helpers if helpers is not None else real_helpers
    raw_first = None
    if isinstance(steps, TaskPlan):
        plan = steps
        raw_first = plan.steps[0].to_dict() if plan.steps else None
    else:
        raw_steps = list(steps)
        raw_first = raw_steps[0] if raw_steps else None
        try:
            plan = normalize_legacy_steps(raw_steps)
        except (PlanValidationError, TypeError) as exc:
            return _failure(0, raw_first, exc)

    try:
        H.ensure_device()
    except Exception as exc:  # noqa: BLE001
        return _failure(0, raw_first, exc)

    policy = PolicyEngine()
    try:
        authorization = policy.authorize(plan, confirmer=confirmer)
    except AuthorizationError as exc:
        step = _authorization_stop(plan, str(exc))
        return _failure(0, step, exc)

    executor = Executor(policy=policy, helpers=H)
    callback = None
    if on_step:
        callback = lambda step, index: on_step(step.to_dict(), index)
    return executor.execute(
        plan, authorization, on_step=callback, max_steps=max_steps).to_dict()


def _authorization_stop(plan: TaskPlan, reason: str) -> dict[str, Any] | None:
    for step in plan.steps:
        if step.id in reason:
            return step.to_dict()
    return plan.steps[0].to_dict() if plan.steps else None


def _failure(steps_run: int, stopped_at: Any, exc: Exception) -> dict[str, Any]:
    return {
        "done": False,
        "steps_run": steps_run,
        "stopped_at": stopped_at,
        "reason": f"{type(exc).__name__}: {exc}",
        "outputs": [],
    }


def plan_from_goal(goal: str) -> Optional[list[Step]]:
    """Small deterministic compatibility planner for one safe goal shape."""
    text = goal.strip()
    if text.lower().startswith("open ") and text[5:].strip():
        return [step_open(text[5:].strip())]
    return None
