"""Code-enforced safety guard (not just prompt-level).

Intercepts or escalates risky actions regardless of what the model was told.
"""
from __future__ import annotations

from typing import Any

_PAY_KEYWORDS = ["支付", "付款", "confirm payment", "pay now", "立即支付",
                 "去支付", "确认支付"]


class SafetyGuard:
    def __init__(self, allow_auto_pay: bool = False):
        self.allow_auto_pay = allow_auto_pay
        self.recent_sends: list[tuple[float, str]] = []

    def check(self, goal: str, action: dict[str, Any],
              page_text: str = "") -> str | None:
        """Return None if the action passes; return a block reason string if
        the action must be intercepted / escalated to the human."""
        t = action.get("type")
        text = str(action.get("text", ""))
        low_page = (page_text or "").lower()
        low_goal = goal.lower()

        # 1. Uninstall requires explicit user intent
        if t == "uninstall_app" and "卸载" not in goal and "uninstall" not in low_goal:
            return "未在用户目标中确认卸载，已拦截"

        # 2. Password-like input on a password page -> escalate
        if t == "input_text":
            if any(k in low_page for k in ["password", "密码"]) and len(text) >= 4:
                return "疑似密码输入，转人工接管"

        # 3. Payment page -> default block auto taps / typing
        if any(k.lower() in low_page for k in _PAY_KEYWORDS):
            if t in {"tap", "input_text"} and not self.allow_auto_pay:
                if any(k in goal for k in ["支付", "下单并支付", "确认付款"]):
                    return "支付确认需人工接管"
                return "检测到支付页，默认拦截自动操作"

        return None
