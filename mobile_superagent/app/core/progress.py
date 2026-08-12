"""Progress tracking / stagnation detection.

Compares the last N steps: foreground package, UI text fingerprint, screenshot
perceptual hash, and action type. If all are identical for `window` steps, the
agent is told to change strategy; after `fail_after` consecutive warnings the
loop fails out.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

try:
    import imagehash
    from PIL import Image
    _HAS_IMAGEHASH = True
except Exception:  # noqa: BLE001
    _HAS_IMAGEHASH = False


@dataclass
class StepFingerprint:
    package: str
    ui_hash: str
    img_hash: str
    action_type: str


class ProgressTracker:
    def __init__(self, window: int = 3, fail_after: int = 5):
        self.window = window
        self.fail_after = fail_after
        self.items: list[StepFingerprint] = []

    @staticmethod
    def _ui_hash(ui_text: str) -> str:
        return hashlib.md5(ui_text.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _img_hash(path: str) -> str:
        if not _HAS_IMAGEHASH or not path:
            return "na"
        try:
            return str(imagehash.average_hash(Image.open(path)))
        except Exception:  # noqa: BLE001
            return "na"

    def add(self, package: str, ui_text: str, screenshot_path: str,
            action_type: str):
        self.items.append(StepFingerprint(
            package=package or "unknown",
            ui_hash=self._ui_hash(ui_text or ""),
            img_hash=self._img_hash(screenshot_path),
            action_type=action_type,
        ))
        self.items = self.items[-10:]

    def stagnant(self) -> bool:
        if len(self.items) < self.window:
            return False
        recent = self.items[-self.window:]
        same_pkg = len({i.package for i in recent}) == 1
        same_ui = len({i.ui_hash for i in recent}) == 1
        same_act = len({i.action_type for i in recent}) == 1
        return same_pkg and same_ui and same_act

    def warning_text(self) -> str:
        return (
            "系统警告：检测到连续多步无进展。"
            "禁止重复相同动作；请改用搜索、返回、重新launch、"
            "其他控件，或 request_user_takeover / respond_to_user 失败说明。"
        )
