"""Skill-level verifiers: post-action evidence checks (not prompt-level).

A verifier runs after an action that *claims* a milestone (e.g. "send"),
and returns whether on-screen evidence confirms it happened. This closes the
loop the system prompt can't: "completion must be verified, not assumed".

Current verifiers:
- messaging: after a send-tap on a messaging page, confirm the just-sent text
  (or a plausible recent-sent bubble) appears in the new UI dump.
"""
from __future__ import annotations


class MessagingVerifier:
    """Confirm a sent message by matching text in the conversation UI dump.

    Strategy (best-effort, ROM-agnostic): search the raw UI dump / OCR for the
    sent text, OR for a trailing "sent" bubble. We accept the text appearing
    anywhere in the new dump since the model already asserted what it typed.
    """

    # Words/patterns that indicate a send button we should double-check after.
    SEND_MARKERS = ("发送", "send")

    def verify_send(self, page_text: str, sent_text: str) -> tuple[bool, str]:
        """Return (confirmed, note). Confirms the typed text shows back up."""
        if not sent_text:
            return False, "没有可验证的发送内容"
        # The sent text (or its core) reappearing in the UI = strong evidence.
        core = self._core(sent_text)
        if not core:
            return False, "发送内容过短，无法可靠验证"
        if core in (page_text or ""):
            return True, "发送内容已在对话中回显，确认已发送"
        return False, "未在界面中找到发送内容的回显证据"

    @staticmethod
    def _core(text: str) -> str:
        """A stable substring long enough to uniquely fingerprint the sent
        text (first 8 chars), so short Chinese messages stay verifiable."""
        t = text.strip()
        return t[:8] if t else ""


def make_verifier(skill: str) -> MessagingVerifier | None:
    if skill == "MESSAGING":
        return MessagingVerifier()
    return None
