"""Policy-gated executor for validated JSON task plans."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from .plan import TaskPlan, TaskStep
from .policy import Authorization, PolicyEngine


@dataclass(frozen=True)
class ExecutionResult:
    done: bool
    steps_run: int
    stopped_at: dict[str, Any] | None
    reason: str
    outputs: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "done": self.done,
            "steps_run": self.steps_run,
            "stopped_at": self.stopped_at,
            "reason": self.reason,
            "outputs": list(self.outputs),
        }


class Executor:
    """Execute data instructions; all safety decisions stay in PolicyEngine."""

    def __init__(self, *, policy: PolicyEngine, helpers: Any) -> None:
        self._policy = policy
        self._helpers = helpers

    def execute(
        self,
        plan: TaskPlan,
        authorization: Authorization,
        *,
        on_step: Callable[[TaskStep, int], None] | None = None,
        max_steps: int = 100,
    ) -> ExecutionResult:
        plan = self._policy.validate(plan)
        steps_run = 0
        outputs: list[Any] = []
        for index, step in enumerate(plan.steps):
            if step.type == "ask":
                continue
            if steps_run >= max_steps:
                return ExecutionResult(
                    False, steps_run, step.to_dict(), "max_steps reached",
                    tuple(outputs))
            try:
                self._policy.assert_authorized(plan, step, authorization)
                if on_step:
                    on_step(step, index)
                output = self._execute_step(step)
                if output is not None:
                    outputs.append(output)
                steps_run += 1
                if step.type not in {"wait", "read_ui"}:
                    self._helpers.wait_stable()
            except Exception as exc:  # noqa: BLE001
                return ExecutionResult(
                    False, steps_run, step.to_dict(),
                    f"{type(exc).__name__}: {exc}", tuple(outputs))
        return ExecutionResult(
            True, steps_run, None, "all steps completed", tuple(outputs))

    def _execute_step(self, step: TaskStep) -> Any:
        args = step.arguments
        step_type = step.type
        if step_type == "open_app":
            target = str(args["target"])
            if "." in target and not target.startswith(" "):
                self._helpers.launch(target)
            else:
                self._helpers.open_app(target)
        elif step_type in {"tap", "send", "purchase", "delete", "install",
                           "change_settings"}:
            return self._helpers.tap_text(
                str(args["target"]), exact=bool(args.get("exact", False)))
        elif step_type == "tap_resource":
            return self._helpers.tap_res_id(str(args["resource_id"]))
        elif step_type == "tap_coordinates":
            return self._helpers.tap(int(args["x"]), int(args["y"]))
        elif step_type == "long_press":
            return self._helpers.long_press(
                int(args["x"]), int(args["y"]),
                float(args.get("duration", 0.8)))
        elif step_type == "type_text":
            self._helpers.type_text(str(args["text"]))
        elif step_type == "type_unicode":
            self._helpers.type_unicode(str(args["text"]))
        elif step_type == "wait":
            time.sleep(float(args.get("seconds", 1.0)))
        elif step_type == "home":
            self._helpers.home()
        elif step_type == "back":
            self._helpers.back()
        elif step_type == "swipe":
            return self._helpers.scroll_screen(
                direction=str(args["direction"]),
                amount=float(args.get("amount", 0.6)))
        elif step_type == "swipe_coordinates":
            return self._helpers.swipe(
                int(args["x1"]), int(args["y1"]),
                int(args["x2"]), int(args["y2"]),
                float(args.get("duration", 0.2)))
        elif step_type == "read_ui":
            return self._helpers.screen_info()
        else:  # Defensive: schema and policy should make this unreachable.
            raise ValueError(f"unsupported executor step: {step_type!r}")
        return None
