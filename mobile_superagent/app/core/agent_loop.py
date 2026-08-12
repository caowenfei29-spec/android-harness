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

    def _emit(self, event: dict):
        if self.on_step:
            self.on_step(event)

    def run(self) -> dict[str, Any]:
        device = self.dm.ensure_online(self.serial)
        state = capture_state(device, self.run_dir, step=0)

        if self.resume_message:
            self.history.append(f"user_resume: {self.resume_message}")

        stagnant_hits = 0
        for step in range(1, self.max_steps + 1):
            device = self.dm.ensure_online(self.serial)

            system_prompt = build_system_prompt(self.skill)
            user_prompt = (
                f"用户目标：\n{self.goal}\n\n"
                f"当前主技能：{self.skill}\n\n"
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

            # record fingerprint (real action type)
            self.progress.add(
                package=state.foreground_package,
                ui_text=state.screen_ocr or state.ui_dump,
                screenshot_path=state.screenshot_path,
                action_type=action.get("type", "unknown"),
            )

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
            self.history.append(
                f"{step}. {json_dumps(action)} => {exec_result.message}")

            if action.get("type") == "request_user_takeover":
                return {"status": "need_user",
                        "reason": action.get("reason", ""),
                        "instruction": action.get("instruction", "")}

            if action.get("type") == "respond_to_user":
                return {"status": agent_out.status
                        if agent_out.status in {"done", "failed"} else "done",
                        "message": action.get("message", "")}

            if agent_out.status in {"done", "failed", "need_user"} \
                    and agent_out.user_message:
                return {"status": agent_out.status,
                        "message": agent_out.user_message,
                        "reason": agent_out.user_message
                        if agent_out.status == "need_user" else None}

            time.sleep(0.5)
            state = capture_state(device, self.run_dir, step=step)

        return {"status": "failed",
                "message": f"超过最大步数 {self.max_steps}"}


def json_dumps(obj) -> str:
    import json
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(obj)
