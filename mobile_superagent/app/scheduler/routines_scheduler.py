"""Routines scheduler (MVP): poll enabled routines, fire due tasks.

Production would use APScheduler; polling is enough for the MVP.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from dateutil.rrule import rrulestr
except Exception:  # noqa: BLE001
    rrulestr = None

from .. import db
from ..worker.runner import start_task_background


def compute_next(rrule_text: str, timezone: str,
                 after: datetime | None = None) -> datetime | None:
    if not rrulestr:
        return None
    after = after or datetime.now(ZoneInfo(timezone or "UTC"))
    try:
        rule = rrulestr(rrule_text, dtstart=after)
        nxt = rule.after(after, inc=False)
        return nxt
    except Exception:  # noqa: BLE001
        return None


def scheduler_loop(poll_seconds: int = 15):
    while True:
        now = datetime.now(ZoneInfo("UTC"))
        for r in db.list_routines(enabled_only=True):
            nxt = r.get("next_run_at")
            if not nxt:
                # no next_run recorded yet -> compute it
                nxt_dt = compute_next(r["rrule"], r["timezone"])
                if nxt_dt:
                    db.update_routine(
                        r["id"], next_run_at=nxt_dt.astimezone(
                            ZoneInfo("UTC")).isoformat())
                continue
            try:
                due = datetime.fromisoformat(nxt) <= now
            except Exception:  # noqa: BLE001
                due = False
            if due:
                task = db.create_task(goal=r["prompt"],
                                      device_id=r["device_id"],
                                      skill_hint=None)
                start_task_background(task["id"])
                db.update_routine(
                    r["id"],
                    last_run_at=now.isoformat(),
                    last_status="fired",
                    next_run_at=None,
                )
        time.sleep(poll_seconds)
