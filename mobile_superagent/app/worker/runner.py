"""Task runner: drive an AgentLoop to completion in a background thread and
persist each step to the DB."""
from __future__ import annotations

import threading
from pathlib import Path

from .. import db
from ..settings import settings
from ..core.agent_loop import AgentLoop
from ..core.device_manager import DeviceManager
from ..core.llm import LLMClient

_dm = DeviceManager()
_llm = LLMClient()
_lock = threading.Lock()


def start_task_background(task_id: str):
    t = threading.Thread(target=run_task, args=(task_id,), daemon=True)
    t.start()


def run_task(task_id: str, resume_message: str | None = None):
    with _lock:  # MVP: global single-task lock
        task = db.get_task(task_id)
        if not task:
            return
        db.update_task(task_id, status="running")
        run_dir = Path(settings.storage_dir) / task_id

        def on_step(event: dict):
            if event.get("type") == "step":
                db.add_step(task_id, event)
                db.update_task(task_id, current_step=event.get("step", 0))

        # resolve device serial by device_id
        dev = db.get_device(task["device_id"]) or {}
        serial = dev.get("serial") or task["device_id"]

        loop = AgentLoop(
            goal=task["user_goal"],
            serial=serial,
            run_dir=run_dir,
            device_manager=_dm,
            llm=_llm,
            skill_hint=task.get("skill_hint"),
            max_steps=settings.max_steps,
            on_step=on_step,
            resume_message=resume_message,
        )
        result = loop.run()

        status = result.get("status", "failed")
        if status == "need_user":
            db.update_task(task_id, status="need_user",
                           need_user_reason=result.get("reason"),
                           need_user_instruction=result.get("instruction"))
        elif status == "done":
            db.update_task(task_id, status="done",
                           result_message=result.get("message", ""))
        else:
            db.update_task(task_id, status="failed",
                           result_message=result.get("message", ""))
