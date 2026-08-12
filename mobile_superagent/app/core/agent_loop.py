"""Agent loop: the reactive observe -> decide -> execute -> verify loop.

Per the product spec (5.3), each round:
  device online check
  screenshot + UI dump + foreground package (+ OCR of the screenshot)
  no-progress detection (code layer)
  assemble prompt (system + active skill + state + history)
  call LLM
  validate JSON / action
  safety guard intercept
  execute action
  persist step + screenshot
  decide whether to end / takeover
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .device_manager import DeviceManager
from .llm import LLMClient
from .schema import extract_json, parse_agent_output
from .skill_loader import build_system_prompt
from .router import route_skill
from .progress import ProgressTracker
from .safety import SafetyGuard
from .perception import capture_state, state_to_prompt
from .verifier import make_verifier
from .. import db

# Skills whose only useful signal is on-screen rendered text (video feeds,
# subtitles) that uiautomator can't see — OCR is expensive, so gate it.
_OCR_SKILLS = {"FEED_SUMMARY", "SOCIAL", "SHOPPING", "BROWSER", "NONE"}

# Built-in app name -> package alias table, injected so the model can launch
# apps by friendly name without guessing package names.
APP_ALIASES = {
    "抖音": "com.ss.android.ugc.aweme",
    "快手": "com.smile.gifmaker",
    "微信": "com.tencent.mm",
    "QQ": "com.tencent.mobileqq",
    "哔哩哔哩": "tv.danmaku.bili",
    "b站": "tv.danmaku.bili",
    "淘宝": "com.taobao.taobao",
    "京东": "com.jingdong.app.mall",
    "小红书": "com.xingin.xhs",
    "微博": "com.sina.weibo",
    "支付宝": "com.eg.android.AlipayGphone",
    "浏览器": "mark.via",
    "via": "mark.via",
    "chrome": "com.android.chrome",
    "youtube": "com.google.android.youtube",
    "应用商店": "com.oppo.market",
    "电话": "com.android.dialer",
    "相机": "com.oppo.camera",
    "相册": "com.coloros.gallery3d",
    "设置": "com.android.settings",
    "邮件": "com.oppo.email",
    "日历": "com.coloros.calendar",
    "地图": "com.autonavi.minimap",
    "美团": "com.sankuai.meituan",
    "滴滴": "com.sdu.didi.psnger",
    "钉钉": "com.alibaba.android.rimet",
    "飞书": "com.ss.android.lark",
    "今日头条": "com.ss.android.article.news",
    "腾讯视频": "com.tencent.qqlive",
    "爱奇艺": "com.qiyi.video",
    "网易云音乐": "com.netease.cloudmusic",
    "拼多多": "com.xunmeng.pinduoduo",
    "闲鱼": "com.taobao.idlefish",
}


class AgentLoop:
    def __init__(self, *, goal: str, serial: str, run_dir: Path,
                 device_manager: DeviceManager, llm: LLMClient,
                 skill_hint: str | None = None, max_steps: int = 40,
                 on_step: Callable[[dict], None] | None = None,
                 resume_message: str | None = None):
        self.goal = goal
        self.serial = serial
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.dm = device_manager
        self.llm = llm
        self.skill = route_skill(goal, skill_hint)
        self.max_steps = max_steps
        self.on_step = on_step
        self.resume_message = resume_message

        self.progress = ProgressTracker()
        self.safety = SafetyGuard()
        self.history: list[str] = []
        self.messages: list[dict] = []
        # OCR is gated by skill: only feed-like skills need on-screen rendered
        # text (video titles). APP_INSTALL etc. save the OCR cost per step.
        self.ocr = self.skill in _OCR_SKILLS
        self.profile = db.get_profile() or {}
        self.verifier = make_verifier(self.skill)
        self.last_action_text = ""  # text of the last input/send action
        # Structured history (JSON-able) for audit/replay; prompt uses the
        # flattened strings in `history`.
        self.steps: list[dict] = []

    def _emit(self, event: dict):
        if self.on_step:
            self.on_step(event)

    def _target_package(self) -> str | None:
        """Best-effort: extract a target package from the goal via the alias
        table, so the state can report whether the app is installed."""
        g = self.goal
        for alias, pkg in APP_ALIASES.items():
            if alias and alias in g:
                return pkg
        return None

    def run(self) -> dict[str, Any]:
        device = self.dm.ensure_online(self.serial)
        target_pkg = self._target_package()
        state = capture_state(device, self.run_dir, step=0, ocr=self.ocr,
                              target_package=target_pkg)

        if self.resume_message:
            self.history.append(f"user_resume: {self.resume_message}")

        # User profile & app aliases injected once into every prompt, so the
        # model knows the user's preferred browser / messaging defaults and
        # can launch apps by friendly name.
        aliases = "\n".join(f"{k} = {v}" for k, v in APP_ALIASES.items())
        profile_hint = self._profile_hint()

        stagnant_hits = 0
        for step in range(1, self.max_steps + 1):
            device = self.dm.ensure_online(self.serial)

            system_prompt = build_system_prompt(self.skill)
            user_prompt = (
                f"用户目标：\n{self.goal}\n\n"
                f"当前主技能：{self.skill}\n\n"
                f"【应用别名表（launch_app 用包名）】\n{aliases}\n\n"
                f"【用户偏好】\n{profile_hint}\n\n"
                f"{state_to_prompt(state)}\n\n"
                f"最近历史动作：\n"
                + ("\n".join(self.history[-12:]) if self.history else "（无）")
                + "\n\n请输出下一个 JSON 动作。"
            )
            if self.progress.stagnant():
                stagnant_hits += 1
                user_prompt += "\n\n" + self.progress.warning_text()
                if stagnant_hits >= 5:
                    result = {"status": "failed",
                              "message": "连续多步无进展，已停止"}
                    self._emit({"type": "final", **result})
                    return result
            else:
                stagnant_hits = 0

            self.messages.append({"role": "user", "content": user_prompt})
            raw = self.llm.chat(system_prompt, self.messages[-12:])
            self.messages.append({"role": "assistant", "content": raw})

            try:
                data = extract_json(raw)
                agent_out, action = parse_agent_output(data)
            except Exception as e:  # noqa: BLE001
                self.history.append(f"{step}. parse_error: {e}")
                self.messages.append({
                    "role": "user",
                    "content": f"输出解析失败：{e}。请只输出合法 JSON。",
                })
                continue

            # safety guard (code-enforced)
            block = self.safety.check(self.goal, action,
                                      page_text=state.screen_ocr or
                                      state.ui_dump)
            if block:
                event = {
                    "type": "step", "step": step, "status": "need_user",
                    "observe": agent_out.observe,
                    "plan": f"安全护栏拦截：{block}",
                    "action": {"type": "request_user_takeover",
                               "reason": block,
                               "instruction": "请手动完成敏感步骤后点继续"},
                }
                self._emit(event)
                return {"status": "need_user", "reason": block,
                        "instruction": "请手动完成敏感步骤后点继续"}

            # execute
            exec_result = device.execute(action)

            # --- launch verification (hard, code-level, not prompt-level) ---
            # A launch_app must actually land on the target package. If the
            # command was issued but the foreground didn't switch, inject the
            # REAL state so the model can't claim "启动成功" and report done.
            launch_unconfirmed = False
            if action.get("type") == "launch_app":
                if not exec_result.ok:
                    launch_unconfirmed = True
                    inst = exec_result.data.get("installed")
                    inst_txt = "未安装" if inst is False else \
                        ("已安装" if inst is True else "未知")
                    self.history.append(
                        f"{step}. launch_app 未确认前台切换！exec={exec_result.message} "
                        f"目标包安装状态: {inst_txt}。"
                        f"若用户目标是安装：未安装则去应用商店搜索安装；"
                        f"若已安装则重试启动或处理拦截弹窗。"
                        f"不得谎报'启动成功/安装完成'。")
                else:
                    self.history.append(
                        f"{step}. launch_app 前台已确认: "
                        f"{exec_result.data.get('foreground')}")

            # remember text for send-verification on messaging
            if action.get("type") in ("input_text", "set_clipboard"):
                self.last_action_text = str(action.get("text", ""))

            # record fingerprint (real action type)
            self.progress.add(
                package=state.foreground_package,
                ui_text=state.screen_ocr or state.ui_dump,
                screenshot_path=state.screenshot_path,
                action_type=action.get("type", "unknown"),
            )

            # messaging send-verifier: after a send tap on a messaging page,
            # re-capture the screen and confirm the typed text reappears as
            # evidence (completion must be verified, not assumed).
            is_send_tap = (
                self.verifier and action.get("type") == "tap"
                and self.last_action_text
                and any(m in (state.screen_ocr or state.ui_dump)
                        for m in ("发送", "send"))
            )
            if is_send_tap:
                try:
                    device.wait_stable(timeout=3.0)
                except Exception:  # noqa: BLE001
                    time.sleep(0.6)
                post = capture_state(device, self.run_dir, step=step,
                                     ocr=self.ocr, target_package=target_pkg)
                ok, note = self.verifier.verify_send(
                    post.screen_ocr or post.ui_dump, self.last_action_text)
                if ok:
                    event = {
                        "type": "step", "step": step,
                        "observe": agent_out.observe,
                        "review": agent_out.review,
                        "plan": agent_out.plan,
                        "skill": agent_out.skill or self.skill,
                        "status": "done",
                        "action": action,
                        "exec_result": exec_result.__dict__(),
                        "screenshot_path": post.screenshot_path,
                        "foreground_package": post.foreground_package,
                        "verified": note,
                    }
                    self._emit(event)
                    return {"status": "done", "message": note}
                # not confirmed — tell the model so it can retry/adapt
                self.history.append(
                    f"{step}. send-verify: {note}（发送证据未确认，勿重复点发送）")

            event = {
                "type": "step", "step": step,
                "observe": agent_out.observe, "review": agent_out.review,
                "plan": agent_out.plan, "skill": agent_out.skill or self.skill,
                "status": agent_out.status, "action": action,
                "exec_result": exec_result.__dict__(),
                "screenshot_path": state.screenshot_path,
                "foreground_package": state.foreground_package,
                "user_message": agent_out.user_message,
            }
            self._emit(event)
            # structured history (audit/replay), JSON-able
            self.steps.append({
                "step": step,
                "observe": agent_out.observe,
                "review": agent_out.review,
                "plan": agent_out.plan,
                "skill": agent_out.skill or self.skill,
                "action": action,
                "action_type": action.get("type"),
                "result": exec_result.message,
                "package": state.foreground_package,
                "screenshot": state.screenshot_path,
            })
            self.history.append(
                f"{step}. {json_dumps(action)} => {exec_result.message}")

            if action.get("type") == "request_user_takeover":
                return {"status": "need_user",
                        "reason": action.get("reason", ""),
                        "instruction": action.get("instruction", "")}

            if action.get("type") == "respond_to_user":
                # Hard guard: never let the model report "启动成功/安装完成"
                # when a launch_app just failed to reach the foreground.
                if launch_unconfirmed:
                    msg = action.get("message", "")
                    if any(k in msg for k in ("启动成功", "安装完成", "已安装",
                                              "启动成功并", "已启动")):
                        self._emit({
                            "type": "step", "step": step,
                            "status": "need_user",
                            "observe": agent_out.observe,
                            "plan": "检测到 launch 未确认前台切换却被报告成功，"
                                    "已拦截谎报。请先在手机上核实目标应用状态。",
                            "action": {"type": "request_user_takeover",
                                       "reason": "launch_app 前台切换未确认，"
                                                 "需人工核实",
                                       "instruction": "请在手机确认目标应用状态后点继续"},
                        })
                        return {"status": "need_user",
                                "reason": "launch_app 前台切换未确认，需人工核实",
                                "instruction": "请在手机确认目标应用状态后点继续"}
                return {"status": agent_out.status
                        if agent_out.status in {"done", "failed"} else "done",
                        "message": action.get("message", "")}

            if agent_out.status in {"done", "failed", "need_user"} \
                    and agent_out.user_message:
                return {"status": agent_out.status,
                        "message": agent_out.user_message,
                        "reason": agent_out.user_message
                        if agent_out.status == "need_user" else None}

            # settle the screen (lazy-loaded content / animations) before the
            # next perception pass — only when an action may have changed the
            # screen (skip for pure read/wait steps to save a dump).
            if action.get("type") not in {"get_state", "wait"}:
                try:
                    device.wait_stable(timeout=3.0)
                except Exception:  # noqa: BLE001
                    time.sleep(0.5)
            else:
                time.sleep(0.5)
            state = capture_state(device, self.run_dir, step=step,
                                  ocr=self.ocr, target_package=target_pkg)

        return {"status": "failed",
                "message": f"超过最大步数 {self.max_steps}"}

    def _profile_hint(self) -> str:
        """Render user-profile prefs into a compact hint for the model."""
        p = self.profile
        if not p:
            return "（无额外偏好）"
        lines = []
        browser = p.get("default_browser")
        if browser:
            lines.append(f"默认浏览器：{browser}")
        if p.get("messaging_paste_first"):
            lines.append("消息发送偏好：先粘贴再发送（paste-first）")
        lang = p.get("language")
        if lang:
            lines.append(f"语言：{lang}")
        auto_pay = p.get("auto_pay")
        if auto_pay is not None:
            lines.append(f"自动支付：{'允许' if auto_pay else '禁止（支付一律人工接管）'}")
        return "\n".join(lines) if lines else "（无额外偏好）"


def json_dumps(obj) -> str:
    import json
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(obj)
