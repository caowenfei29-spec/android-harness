"""SQLite persistence for mobile_superagent.

MVP uses stdlib sqlite3 (no ORM dependency). Schema matches the product spec.
Thread-safe via a module-level lock + per-call connections.
"""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .settings import settings

_db_path = Path(settings.db_url.replace("sqlite:///", ""))
_db_path.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY, name TEXT, serial TEXT UNIQUE,
  connect_type TEXT, status TEXT, last_seen_at TEXT, props_json TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, device_id TEXT, user_goal TEXT, status TEXT,
  skill_hint TEXT, current_step INTEGER DEFAULT 0,
  need_user_reason TEXT, need_user_instruction TEXT, result_message TEXT,
  created_at TEXT, started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS task_steps (
  id TEXT PRIMARY KEY, task_id TEXT, step_no INTEGER,
  observe TEXT, review TEXT, plan TEXT, skill TEXT,
  action_json TEXT, exec_result_json TEXT, screenshot_path TEXT,
  foreground_package TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS routines (
  id TEXT PRIMARY KEY, title TEXT, prompt TEXT, device_id TEXT,
  rrule TEXT, timezone TEXT, enabled INTEGER, next_run_at TEXT,
  last_run_at TEXT, last_status TEXT
);
CREATE TABLE IF NOT EXISTS user_profile (
  id TEXT PRIMARY KEY, data_json TEXT
);
"""


def _conn():
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _lock:
        conn = _conn()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# --- devices --------------------------------------------------------------

def upsert_device(serial: str, name: str = "", connect_type: str = "usb",
                  props: dict | None = None):
    with _lock:
        conn = _conn()
        try:
            rid = "dev_" + serial[-6:]
            props_json = json.dumps(props or {}, ensure_ascii=False)
            conn.execute(
                """INSERT INTO devices (id,name,serial,connect_type,status,
                       last_seen_at,props_json)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(serial) DO UPDATE SET
                     name=excluded.name, status=excluded.status,
                     last_seen_at=excluded.last_seen_at,
                     props_json=excluded.props_json""",
                (rid, name, serial, connect_type, "online", _now(), props_json))
            conn.commit()
            return rid
        finally:
            conn.close()


def list_devices():
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute("SELECT * FROM devices").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_device(device_id: str):
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def device_by_serial(serial: str):
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM devices WHERE serial=?", (serial,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


# --- tasks ----------------------------------------------------------------

def create_task(goal: str, device_id: str, skill_hint: str | None = None):
    tid = "task_" + uuid.uuid4().hex[:10]
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """INSERT INTO tasks (id,device_id,user_goal,status,skill_hint,
                       current_step,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (tid, device_id, goal, "queued", skill_hint, 0, _now()))
            conn.commit()
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            return dict(row)
        finally:
            conn.close()


def get_task(task_id: str):
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def update_task(task_id: str, **fields):
    with _lock:
        conn = _conn()
        try:
            cols = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE tasks SET {cols} WHERE id=?",
                (*fields.values(), task_id))
            conn.commit()
        finally:
            conn.close()


def list_tasks(limit=50):
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# --- task_steps -----------------------------------------------------------

def add_step(task_id: str, event: dict):
    with _lock:
        conn = _conn()
        try:
            sid = "step_" + uuid.uuid4().hex[:10]
            step_no = event.get("step", 0)
            conn.execute(
                """INSERT INTO task_steps
                   (id,task_id,step_no,observe,review,plan,skill,
                    action_json,exec_result_json,screenshot_path,
                    foreground_package,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, task_id, step_no,
                 event.get("observe", ""), event.get("review", ""),
                 event.get("plan", ""), event.get("skill", ""),
                 json.dumps(event.get("action") or {}, ensure_ascii=False),
                 json.dumps(event.get("exec_result") or {}, ensure_ascii=False),
                 event.get("screenshot_path"), event.get("foreground_package"),
                 _now()))
            conn.commit()
        finally:
            conn.close()


def list_steps(task_id: str):
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT * FROM task_steps WHERE task_id=? ORDER BY step_no",
                (task_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# --- routines -------------------------------------------------------------

def create_routine(title: str, prompt: str, device_id: str, rrule: str,
                   timezone: str, next_run_at: str | None = None):
    rid = "routine_" + uuid.uuid4().hex[:10]
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """INSERT INTO routines
                   (id,title,prompt,device_id,rrule,timezone,enabled,
                    next_run_at,last_run_at,last_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (rid, title, prompt, device_id, rrule, timezone, 1,
                 next_run_at, None, None))
            conn.commit()
            row = conn.execute(
                "SELECT * FROM routines WHERE id=?", (rid,)).fetchone()
            return dict(row)
        finally:
            conn.close()


def list_routines(enabled_only=False):
    with _lock:
        conn = _conn()
        try:
            sql = "SELECT * FROM routines"
            if enabled_only:
                sql += " WHERE enabled=1"
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_routine(routine_id: str):
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM routines WHERE id=?", (routine_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def update_routine(routine_id: str, **fields):
    with _lock:
        conn = _conn()
        try:
            cols = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE routines SET {cols} WHERE id=?",
                (*fields.values(), routine_id))
            conn.commit()
        finally:
            conn.close()


def delete_routine(routine_id: str):
    with _lock:
        conn = _conn()
        try:
            conn.execute("DELETE FROM routines WHERE id=?", (routine_id,))
            conn.commit()
        finally:
            conn.close()


# --- user_profile ---------------------------------------------------------

def get_profile():
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT data_json FROM user_profile WHERE id='main'").fetchone()
            if row:
                return json.loads(row["data_json"])
            return {}
        finally:
            conn.close()


def set_profile(data: dict):
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """INSERT INTO user_profile (id,data_json) VALUES ('main',?)
                   ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json""",
                (json.dumps(data, ensure_ascii=False),))
            conn.commit()
        finally:
            conn.close()
