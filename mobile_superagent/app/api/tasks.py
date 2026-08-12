"""Task API: create, query, steps, continue, cancel."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

from .. import db
from ..settings import settings
from ..worker.runner import run_task, start_task_background

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class CreateTaskReq(BaseModel):
    goal: str
    device_id: str
    skill_hint: str | None = None


class ContinueReq(BaseModel):
    message: str = ""


@router.get("/{task_id}/screenshots/{step_no}")
def get_screenshot(task_id: str, step_no: int):
    """Serve the PNG for a given step, resolving both naming schemes."""
    base = Path(settings.storage_dir) / task_id
    for cand in (f"step{step_no:02d}.png", f"step_{step_no:03d}.png",
                 f"step_{step_no}.png", f"step{step_no}.png"):
        p = base / cand
        if p.exists():
            return FileResponse(str(p), media_type="image/png")
    return {"error": "screenshot not found"}


@router.post("")
def create_task(req: CreateTaskReq):
    task = db.create_task(goal=req.goal, device_id=req.device_id,
                          skill_hint=req.skill_hint)
    start_task_background(task["id"])
    return task


@router.get("")
def list_tasks(limit: int = 50):
    return db.list_tasks(limit=limit)


@router.get("/{task_id}")
def get_task(task_id: str):
    return db.get_task(task_id)


@router.get("/{task_id}/steps")
def get_steps(task_id: str):
    return db.list_steps(task_id)


@router.post("/{task_id}/continue")
def continue_task(task_id: str, req: ContinueReq):
    task = db.get_task(task_id)
    if not task or task["status"] != "need_user":
        return {"error": "task not waiting for user"}
    db.update_task(task_id, status="queued", need_user_reason=None,
                   need_user_instruction=None)
    run_task(task_id, req.message)
    return {"ok": True}


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    db.update_task(task_id, status="cancelled")
    return {"ok": True}
