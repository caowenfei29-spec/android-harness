"""Skill routing: map a natural-language goal to a primary skill."""
from __future__ import annotations


def route_skill(goal: str, skill_hint: str | None = None) -> str:
    if skill_hint:
        return skill_hint
    g = goal.lower()
    zh = goal

    if any(k in zh for k in ["安装", "卸载"]) or "install" in g or "uninstall" in g:
        return "APP_INSTALL"
    if any(k in zh for k in ["发送", "回复", "微信", "消息", "短信", "私信"]):
        return "MESSAGING"
    if any(k in zh for k in ["刷", "视频", "信息流", "抖音", "快手", "youtube",
                             "摘要"]):
        return "FEED_SUMMARY"
    if any(k in zh for k in ["定时", "每天", "每周", "例行", "routine"]):
        return "ROUTINES"
    if any(k in zh for k in ["支付", "下单并支付", "确认付款"]):
        return "SAFETY_TAKEOVER"
    # safe default: browsing/navigation is the least destructive
    return "BROWSER"
