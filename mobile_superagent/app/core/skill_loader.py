"""Skill loading: build the system prompt as base + safety + ONE active skill.

Keeps token cost low (only the routed skill doc is appended, not all of them).
"""
from pathlib import Path

from ..settings import settings

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

SKILL_MAP = {
    "APP_INSTALL": "skills/app_install.md",
    "MESSAGING": "skills/messaging.md",
    "BROWSER": "skills/browser.md",
    "FEED_SUMMARY": "skills/feed_summary.md",
    "ROUTINES": "skills/routines.md",
    "SAFETY": "skills/safety.md",
}


def load_text(rel: str) -> str:
    p = PROMPTS_DIR / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def build_system_prompt(skill: str | None = None) -> str:
    parts = [load_text("system.md"), load_text(SKILL_MAP["SAFETY"])]
    parts = [p for p in parts if p]
    if skill and skill in SKILL_MAP and skill != "SAFETY":
        extra = load_text(SKILL_MAP[skill])
        if extra:
            parts.append(extra)
    return "\n\n".join(parts)
