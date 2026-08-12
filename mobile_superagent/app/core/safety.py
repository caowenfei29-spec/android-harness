"""Code-enforced safety guard (not just prompt-level).

Intercepts or escalates risky actions regardless of what the model was told.
"""
from __future__ import annotations

import time
from typing import Any

_PAY_KEYWORDS = ["支付", "付款", "confirm payment", "pay now", "立即支付",
                 "去支付", "确认支付"]


class SafetyGuard:
    # "send"-like action text near the tap target → throttle repeated sends.
    _SEND_LABELS = ("发送", "send", "发送给", "完成", "确认发送")

    def __init__(self, allow_auto_pay: bool = False, send_min_interval: float = 3.0):
        self.allow_auto_pay = allow_auto_pay
        self.send_min_interval = send_min_interval
        self.recent_sends: list[tuple[float, str]] = []

    def _check_send_rate(self, page_text: str) -> str | None:
        """Throttle repeated "send" taps near the send button. Returns a block
        reason if two send-taps land too close together (double-send guard).

        Records every passing send-tap so the next one is compared against it.
        """
        if not any(k in page_text for k in self._SEND_LABELS):
            return None
        now = time.time()
        # prune old entries
        self.recent_sends = [(ts, s) for ts, s in self.recent_sends
                             if now - ts < 30]
        if self.recent_sends:
            last_ts, _ = self.recent_sends[-1]
            if now - last_ts < self.send_min_interval:
                return "检测到连续发送间隔过短，已拦截（防重复发送）"
        # this send-tap passed — remember it for the next comparison
        self.recent_sends.append((now, page_text[:80]))
        return None

    def check(self, goal: str, action: dict[str, Any],
              page_text: str = "") -> str | None:
        """Return None if the action passes; return a block reason string if
        the action must be intercepted / escalated to the human."""
        t = action.get("type")
        text = str(action.get("text", ""))
        low_page = (page_text or "").lower()
        low_goal = goal.lower()

        # 0. throttle repeated sends on messaging pages
        if t == "tap":
            block_rate = self._check_send_rate(page_text or "")
            if block_rate:
                return block_rate

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
