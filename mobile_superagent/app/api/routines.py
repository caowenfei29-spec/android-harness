"""Routines API: CRUD + enable/disable."""
from fastapi import APIRouter
from pydantic import BaseModel

from .. import db
from ..scheduler.routines_scheduler import compute_next

router = APIRouter(prefix="/api/routines", tags=["routines"])


class CreateRoutineReq(BaseModel):
    title: str
    prompt: str
    device_id: str
    rrule: str
    timezone: str = "Asia/Shanghai"


class UpdateRoutineReq(BaseModel):
    title: str | None = None
    prompt: str | None = None
    rrule: str | None = None
    timezone: str | None = None


@router.get("")
def list_routines():
    return db.list_routines()


@router.post("")
def create_routine(req: CreateRoutineReq):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    nxt = compute_next(req.rrule, req.timezone)
    next_run_at = nxt.astimezone(ZoneInfo("UTC")).isoformat() if nxt else None
    return db.create_routine(req.title, req.prompt, req.device_id, req.rrule,
                             req.timezone, next_run_at)


@router.patch("/{routine_id}")
def update_routine(routine_id: str, req: UpdateRoutineReq):
    fields = req.model_dump(exclude_none=True)
    if fields:
        db.update_routine(routine_id, **fields)
    return db.get_routine(routine_id)


@router.post("/{routine_id}/enable")
def enable_routine(routine_id: str):
    db.update_routine(routine_id, enabled=1)
    return {"ok": True}


@router.post("/{routine_id}/disable")
def disable_routine(routine_id: str):
    db.update_routine(routine_id, enabled=0)
    return {"ok": True}


@router.delete("/{routine_id}")
def delete_routine(routine_id: str):
    db.delete_routine(routine_id)
    return {"ok": True}
