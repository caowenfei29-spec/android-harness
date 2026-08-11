"""Strict, data-only task plans for android-harness.

Plans are the only input accepted by the safe executor.  They deliberately
contain no expressions, callbacks, imports, or executable source code.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence


PLAN_VERSION = 1
MAX_STEPS = 100
MAX_STRING_LENGTH = 4096


class PlanValidationError(ValueError):
    """Raised when untrusted JSON is not a valid task plan."""


_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "open_app": ({"target"}, {"id"}),
    "tap": ({"target"}, {"id", "exact"}),
    "tap_resource": ({"resource_id"}, {"id"}),
    "tap_coordinates": ({"x", "y"}, {"id"}),
    "long_press": ({"x", "y"}, {"id", "duration"}),
    "type_text": ({"text"}, {"id"}),
    "type_unicode": ({"text"}, {"id"}),
    "wait": (set(), {"id", "seconds"}),
    "home": (set(), {"id"}),
    "back": (set(), {"id"}),
    "swipe": ({"direction"}, {"id", "amount"}),
    "swipe_coordinates": ({"x1", "y1", "x2", "y2"}, {"id", "duration"}),
    "read_ui": (set(), {"id"}),
    "ask": ({"prompt"}, {"id"}),
    "send": ({"target"}, {"id", "exact"}),
    "purchase": ({"target"}, {"id", "exact"}),
    "delete": ({"target"}, {"id", "exact"}),
    "install": ({"target"}, {"id", "exact"}),
    "change_settings": ({"target"}, {"id", "exact"}),
}


@dataclass(frozen=True)
class TaskStep:
    """One validated executor instruction."""

    id: str
    type: str
    arguments: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, **dict(self.arguments)}


@dataclass(frozen=True)
class TaskPlan:
    """A versioned sequence of validated, data-only steps."""

    steps: tuple[TaskStep, ...]
    version: int = PLAN_VERSION

    @classmethod
    def from_dict(cls, value: Any) -> "TaskPlan":
        if isinstance(value, list):
            value = {"version": PLAN_VERSION, "steps": value}
        if not isinstance(value, dict):
            raise PlanValidationError("plan must be a JSON object")
        unknown = set(value) - {"version", "steps"}
        if unknown:
            raise PlanValidationError(
                "unknown plan fields: " + ", ".join(sorted(unknown)))
        version = value.get("version", PLAN_VERSION)
        if version != PLAN_VERSION:
            raise PlanValidationError(f"unsupported plan version: {version!r}")
        raw_steps = value.get("steps")
        if not isinstance(raw_steps, list):
            raise PlanValidationError("plan.steps must be a JSON array")
        if len(raw_steps) > MAX_STEPS:
            raise PlanValidationError(f"plan exceeds {MAX_STEPS} steps")

        steps: list[TaskStep] = []
        ids: set[str] = set()
        for index, raw in enumerate(raw_steps):
            step = _parse_step(raw, index)
            if step.id in ids:
                raise PlanValidationError(f"duplicate step id: {step.id!r}")
            ids.add(step.id)
            steps.append(step)
        return cls(tuple(steps), version)

    @classmethod
    def from_json(cls, source: str | bytes) -> "TaskPlan":
        try:
            value = json.loads(source)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PlanValidationError(f"invalid JSON task plan: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version,
                "steps": [step.to_dict() for step in self.steps]}

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def digest(self) -> str:
        canonical = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _parse_step(raw: Any, index: int) -> TaskStep:
    if not isinstance(raw, dict):
        raise PlanValidationError(f"steps[{index}] must be a JSON object")
    step_type = raw.get("type")
    if not isinstance(step_type, str) or step_type not in _FIELDS:
        raise PlanValidationError(
            f"steps[{index}].type is not an allowed executor capability")
    required, optional = _FIELDS[step_type]
    allowed = {"type"} | required | optional
    unknown = set(raw) - allowed
    missing = required - set(raw)
    if unknown:
        raise PlanValidationError(
            f"steps[{index}] has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise PlanValidationError(
            f"steps[{index}] is missing: {', '.join(sorted(missing))}")

    step_id = raw.get("id", f"step-{index + 1}")
    _require_string(step_id, f"steps[{index}].id", allow_empty=False)
    arguments = {key: value for key, value in raw.items()
                 if key not in {"id", "type"}}
    for key, value in arguments.items():
        if key in {"target", "resource_id", "text", "prompt", "direction"}:
            _require_string(value, f"steps[{index}].{key}", allow_empty=False)
        elif key == "exact":
            if not isinstance(value, bool):
                raise PlanValidationError(f"steps[{index}].exact must be boolean")
        elif key in {"seconds", "amount", "duration", "x", "y", "x1", "y1",
                     "x2", "y2"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)):
                raise PlanValidationError(f"steps[{index}].{key} must be finite")
    if step_type == "wait" and not 0 <= float(arguments.get("seconds", 1.0)) <= 30:
        raise PlanValidationError(f"steps[{index}].seconds must be between 0 and 30")
    if step_type == "swipe":
        if arguments["direction"] not in {"up", "down"}:
            raise PlanValidationError(f"steps[{index}].direction must be up or down")
        if not 0.1 <= float(arguments.get("amount", 0.6)) <= 1.0:
            raise PlanValidationError(f"steps[{index}].amount must be between 0.1 and 1.0")
    if "duration" in arguments and not 0 <= float(arguments["duration"]) <= 10:
        raise PlanValidationError(f"steps[{index}].duration must be between 0 and 10")
    for coordinate in {"x", "y", "x1", "y1", "x2", "y2"} & set(arguments):
        value = float(arguments[coordinate])
        if value < 0 or value > 100000 or not value.is_integer():
            raise PlanValidationError(
                f"steps[{index}].{coordinate} must be a non-negative integer")
    return TaskStep(step_id, step_type, arguments)


def _require_string(value: Any, field: str, *, allow_empty: bool) -> None:
    if not isinstance(value, str):
        raise PlanValidationError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise PlanValidationError(f"{field} must not be empty")
    if len(value) > MAX_STRING_LENGTH:
        raise PlanValidationError(f"{field} exceeds {MAX_STRING_LENGTH} characters")


def normalize_legacy_steps(steps: Sequence[Mapping[str, Any]]) -> TaskPlan:
    """Convert the historical task helper dictionaries into a TaskPlan."""
    mapping = {
        "open": ("open_app", {"app": "target"}),
        "tap": ("tap", {"text": "target"}),
        "tap_id": ("tap_resource", {"res_id": "resource_id"}),
        "type": ("type_text", {}),
        "type_unicode": ("type_unicode", {}),
        "wait": ("wait", {}),
        "ask": ("ask", {}),
    }
    converted = []
    for raw in steps:
        if not isinstance(raw, Mapping):
            raise PlanValidationError("legacy task steps must be mappings")
        op = raw.get("op")
        if op not in mapping:
            raise PlanValidationError(f"unknown legacy task op: {op!r}")
        step_type, renames = mapping[op]
        item = {"type": step_type}
        for key, value in raw.items():
            if key == "op":
                continue
            item[renames.get(key, key)] = value
        converted.append(item)
    return TaskPlan.from_dict({"version": PLAN_VERSION, "steps": converted})
