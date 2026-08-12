"""Protocol schema: parse the model's JSON action output into typed objects.

The agent loop emits exactly one JSON object per round (see prompts/system.md).
This module parses that JSON robustly and validates the action against the
whitelist before execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# The whitelist of action types the executor understands.
ACTION_TYPES = {
    "get_state", "launch_app", "tap", "long_press", "swipe", "input_text",
    "set_clipboard", "paste", "back", "home", "wait", "open_url",
    "play_store_search", "uninstall_app", "get_clipboard",
    "request_user_takeover", "respond_to_user",
}

TERMINAL_ACTIONS = {"request_user_takeover", "respond_to_user"}


@dataclass
class AgentOutput:
    observe: str = ""
    review: str = ""
    plan: str = ""
    skill: str = "NONE"
    status: str = "running"
    user_message: str = ""
    action: dict[str, Any] = field(default_factory=dict)


def extract_json(text: str) -> dict:
    """Extract the first { ... } JSON object from a model reply, tolerating
    stray fences / prose. Raises ValueError if none found."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if "```" in t:
            t = t.rsplit("```", 1)[0]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s == -1 or e == -1:
            raise ValueError("model did not return JSON: %s" % text[:200])
        return json.loads(t[s:e + 1])


def parse_agent_output(data: dict) -> tuple[AgentOutput, dict]:
    """Validate a parsed protocol dict. Returns (AgentOutput, action_dict).

    Raises ValueError if the action is missing or off-whitelist.
    """
    action = data.get("action") or {}
    if not isinstance(action, dict) or not action.get("type"):
        raise ValueError("missing action: %s" % str(data)[:200])
    atype = action["type"]
    if atype not in ACTION_TYPES:
        raise ValueError("off-whitelist action type %r" % atype)

    status = data.get("status", "running")
    if status not in {"running", "need_user", "done", "failed"}:
        status = "running"

    out = AgentOutput(
        observe=str(data.get("observe", "")),
        review=str(data.get("review", "")),
        plan=str(data.get("plan", "")),
        skill=str(data.get("skill", "NONE")),
        status=status,
        user_message=str(data.get("user_message", "")),
        action=action,
    )
    return out, action
