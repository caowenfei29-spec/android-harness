"""Task-level convenience wrappers on top of the android_harness primitives.

The primitives (tap_text, scroll_collect, screenshot, ...) are *action-level*:
the agent decides each step. These helpers add a thin *task-level* layer: give
a goal in plain language and let a small local planner loop drive the phone.

This is intentionally NOT a cloud agent. There is no model inside android-
harness. The planner here is a deterministic, readable ruleset over the UI
tree — open X, find Y, tap it, verify — and it explicitly stops and asks the
human before anything outward-facing or hard to reverse (send, post, buy,
delete, change settings, install). For genuinely open-ended goals, delegate to
an external LLM and call the primitives directly.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import adb as _adb


# --- goal vocabulary -------------------------------------------------------
# A task is a small list of steps. Each step is one of the typed helpers
# below. Keeping it data-shaped (not free-form text) means it's auditable and
# needs no model to run. An LLM can still *generate* this list for an open goal.

Step = dict


def step_open(app: str) -> Step:
    """Open an app by launcher label (or package if it looks like one)."""
    return {"op": "open", "app": app}


def step_tap(text: str, exact: bool = False) -> Step:
    """Tap a visible control by its label."""
    return {"op": "tap", "text": text, "exact": exact}


def step_tap_id(res_id: str) -> Step:
    """Tap a visible control by Android resource-id (stable across label changes)."""
    return {"op": "tap_id", "res_id": res_id}


def step_type(text: str) -> Step:
    """Type text into the focused field (ASCII; use step_type_unicode for CJK)."""
    return {"op": "type", "text": text}


def step_type_unicode(text: str) -> Step:
    """Type unicode / CJK via ADBKeyboard broadcast."""
    return {"op": "type_unicode", "text": text}


def step_wait(seconds: float = 1.0) -> Step:
    return {"op": "wait", "seconds": seconds}


def step_ask(prompt: str) -> Step:
    """Pause and ask the human to approve / do something before continuing."""
    return {"op": "ask", "prompt": prompt}


# Outward-facing / hard-to-reverse ops MUST go through step_ask first.
_OUTWARD = {"send", "post", "buy", "delete", "install", "uninstall", "settings"}


def run_task(steps, *, on_step=None, max_steps: int = 50, helpers=None) -> dict:
    """Execute a list of task steps against the connected phone.

    Returns a summary dict:
        {"done": bool, "steps_run": int, "stopped_at": step-or-None,
         "reason": str}

    The loop stops early if the phone disconnects or a step requires human
    input (step_ask). `on_step(step, index)` is an optional callback for
    progress logging / UI.

    Safety: step_ask halts the loop and returns control to the caller; the
    harness never performs an outward action on its own.

    `helpers` is an optional injection point (used by tests); when omitted the
    real android_harness.helpers module is used.
    """
    from . import helpers as _H
    H = helpers if helpers is not None else _H
    try:
        H.ensure_device()
    except Exception as e:  # noqa: BLE001
        return {"done": False, "steps_run": 0, "stopped_at": (steps[0] if steps else None),
                "reason": f"{type(e).__name__}: {e}"}
    steps_run = 0
    for i, step in enumerate(steps):
        if on_step:
            on_step(step, i)
        if steps_run >= max_steps:
            return {"done": False, "steps_run": steps_run, "stopped_at": step,
                    "reason": "max_steps reached"}
        op = step.get("op")
        try:
            if op == "open":
                _open(step["app"], H)
            elif op == "tap":
                H.tap_text(step["text"], exact=step.get("exact", False))
            elif op == "tap_id":
                H.tap_res_id(step["res_id"])
            elif op == "type":
                H.type_text(step["text"])
            elif op == "type_unicode":
                H.type_unicode(step["text"])
            elif op == "wait":
                time.sleep(float(step.get("seconds", 1.0)))
            elif op == "ask":
                return {"done": False, "steps_run": steps_run,
                        "stopped_at": step,
                        "reason": "human input required: " + step.get("prompt", "")}
            else:
                raise ValueError(f"unknown step op: {op!r}")
        except Exception as e:  # noqa: BLE001
            return {"done": False, "steps_run": steps_run, "stopped_at": step,
                    "reason": f"{type(e).__name__}: {e}"}
        steps_run += 1
        H.wait_stable()
    return {"done": True, "steps_run": steps_run, "stopped_at": None,
            "reason": "all steps completed"}


def _open(target: str, H=None) -> None:
    """Open by launcher label, or by package name if it contains a dot."""
    if H is None:
        from . import helpers as H
    if "." in target and not target.startswith(" "):
        _adb.launch(target)
    else:
        H.open_app(target)


def plan_from_goal(goal: str) -> Optional[list]:
    """Very small keyword planner — a stand-in for an external LLM.

    This is deterministic and transparent on purpose: it only recognizes a few
    shapes and returns None for anything it can't map, so the caller knows to
    hand the goal to a real model. It never invents outward actions.
    """
    g = goal.strip().lower()
    if g.startswith("open "):
        app = goal.strip()[5:].strip()
        return [step_open(app)]
    if "send" in g or "post" in g or "buy" in g or "delete" in g:
        # Outward action: refuse to auto-plan; require a human in the loop.
        return None
    return None
