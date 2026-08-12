#!/usr/bin/env python3
"""Local visual control UI for android-harness.

Serves a single-page web app (web/control.html) that mirrors the phone:
live screenshot, click-to-tap, tap-by-label chips, type (ASCII / Chinese),
home / back / swipe, open app, and a Python script console.

Run:
    python web.py [--port 8741] [--host 127.0.0.1]

Or, if installed: `android-harness web`.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_ROOT / "src"))

from android_harness import helpers as H  # noqa: E402
from android_harness import adb as A      # noqa: E402
from android_harness import ui as UI       # noqa: E402
try:
    from llm import translate, summarize, plan, configured as llm_configured
except Exception:  # noqa: BLE001
    translate = summarize = None
    def llm_configured():
        return False
    def plan(*a, **k):
        raise RuntimeError("LLM 模块加载失败")


# Outward / destructive actions that must NEVER run without a human step_ask.
# We use a POSITIVE whitelist (AST-checked) instead of keyword blocking, because
# an LLM can phrase forbidden actions in Chinese or variants that keyword scans
# miss. Only calls to the names below are allowed to execute.
_ALLOWED_CALLS = {
    "launch", "tap_text", "tap_res_id", "scroll_screen", "dump_nodes",
    "screen_info", "run_task",
    "step_open", "step_tap", "step_tap_id", "step_type",
    "step_type_unicode", "step_wait", "step_ask",
    # safe builtins the translator legitimately uses for read/format only
    "print", "len", "range", "list", "str", "int", "dict", "set",
    "enumerate", "zip", "sorted", "tuple", "bool", "float",
    # time.sleep — pure wait, safe (guarded below to only allow via time module)
    "sleep",
}
_IMPORT_ALLOWED = {"time", "json"}


def _safe_code(code: str) -> (bool, str):
    """AST-whitelist check: only allow calls to known read-only / navigation
    harness functions (and step_ask for human confirmation). Rejects anything
    else so an LLM cannot sneak in send/post/buy/delete/install/uninstall or
    arbitrary Python. Returns (ok, reason)."""
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, "翻译出的代码语法错误: %s" % e
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name not in _IMPORT_ALLOWED:
                    return False, "不允许导入模块 '%s'（仅允许 %s）" % (
                        n.name, ", ".join(sorted(_IMPORT_ALLOWED)))
        elif isinstance(node, ast.ImportFrom):
            # Only allow `from android_harness import ...` (the harness API).
            # What it imports is safe — the harness module only exposes the
            # intended surface; the danger is in *calling* unknown functions,
            # which the Call check below handles.
            if getattr(node.module, "split", None) and \
                    node.module.split(".")[0] != "android_harness":
                return False, "不允许从 '%s' 导入（仅允许 android_harness）" % node.module
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name is None:
                return False, "无法识别的调用"
            if name not in _ALLOWED_CALLS:
                return False, (
                    "拦截：翻译代码调用了未授权函数 '%s'。只允许只读/导航操作"
                    "(launch/tap_text/scroll_screen/dump_nodes/run_task 及 step_*)。"
                    "外向动作(发送/购买/删除/安装等)必须由 step_ask 包成确认步骤。" % name)
    return True, ""

WEB_DIR = HARNESS_ROOT / "web"
DEFAULT_PORT = int(os.environ.get("ANDROID_HARNESS_WEB_PORT", "8741"))


def _state():
    st = A.device_state()
    if st != "ready":
        return {"state": st, "size": None, "package": None,
                "activity": None, "adbkeyboard": False}
    size = A.screen_size()
    pkg, act = A.current_app()
    return {"state": st, "size": list(size) if size else None,
            "package": pkg, "activity": act,
            "adbkeyboard": A.adbkeyboard_installed()}


def _require_ready():
    st = A.device_state()
    if st != "ready":
        raise RuntimeError(
            "Phone not connected (state=%s). Plug in USB, enable USB "
            "debugging, approve the prompt, then retry." % st)


# ===========================================================================
# Task engine — Airtap-style: plan -> step-by-step execute with live status
# ===========================================================================
# Each step has {name, code, needs_confirm, confirm_text, status, output}.
# status: pending -> running -> done | error | awaiting_confirm
# Tasks live in a dict keyed by id; a background thread drives them so the
# HTTP request returns immediately and the frontend polls GET /task/<id>.
_TASKS = {}
_TASKS_LOCK = threading.Lock()


def _new_task(plan_text, steps):
    tid = uuid.uuid4().hex[:12]
    task = {
        "id": tid, "plan_text": plan_text,
        "prompt": "", "steps": steps, "status": "planned",
        "result": None, "created": time.time(),
    }
    with _TASKS_LOCK:
        _TASKS[tid] = task
    return task


def _exec_step_code(code, extra):
    """Run one step's code in a namespace with H/A/time, capture stdout."""
    g = dict(extra)
    g["__name__"] = "__main__"
    g.setdefault("time", __import__("time"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, g)
        return {"ok": True, "output": buf.getvalue()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "output": "ERROR: %s: %s" % (type(e).__name__, e)}


def _worker(tid):
    """Drive the task's steps in a background thread, updating status live."""
    task = _TASKS.get(tid)
    if not task:
        return
    task["status"] = "running"
    ns = {"H": H, "A": A, "task": task_mod()}
    for step in task["steps"]:
        step["status"] = "running"
        # confirmation gate: pause and wait for human before outward step
        if step.get("needs_confirm"):
            step["status"] = "awaiting_confirm"
            task["status"] = "awaiting_confirm"
            step["_event"] = threading.Event()
            step["_event"].wait(timeout=3600)
            step.pop("_event", None)
            if task.get("_cancelled"):
                step["status"] = "cancelled"
                task["status"] = "cancelled"
                task["result"] = {"done": False, "reason": "用户取消"}
                return
            step["status"] = "running"
            task["status"] = "running"
        res = _exec_step_code(step["code"], ns)
        step["output"] = res["output"]
        step["status"] = "done" if res["ok"] else "error"
        if not res["ok"]:
            task["status"] = "error"
            task["result"] = {"done": False, "reason": res["output"]}
            return
        try:
            H.wait_stable()
        except Exception:  # noqa: BLE001
            pass
    task["status"] = "done"
    task["result"] = {"done": True, "reason": "全部步骤完成"}


def task_mod():
    from android_harness import task
    return task


def _cancel_task(tid):
    with _TASKS_LOCK:
        t = _TASKS.get(tid)
        if t:
            t["_cancelled"] = True
            for s in t["steps"]:
                if s.get("_event"):
                    s["_event"].set()


def _public_task(t):
    """Serialize a task for the frontend, stripping internal fields."""
    if t is None:
        return None
    steps = []
    for s in t.get("steps", []):
        pub = {k: s.get(k) for k in
               ("name", "code", "needs_confirm", "confirm_text",
                "status", "output")}
        steps.append(pub)
    return {
        "id": t.get("id"), "prompt": t.get("prompt"),
        "plan_text": t.get("plan_text"), "status": t.get("status"),
        "result": t.get("result"), "steps": steps,
        "created": t.get("created"),
    }


def _do_action(op, data):
    if op == "plan":
        if not llm_configured():
            return {"ok": False, "error": "LLM 未配置：在 .env 设置 "
                    "LLM_BASE_URL/LLM_API_KEY/LLM_MODEL"}
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            return {"ok": False, "error": "空指令"}
        try:
            plan_data = plan(prompt)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "规划失败: %s" % e}
        # AST-whitelist each step now (fail fast before any execution)
        steps = []
        for s in plan_data.get("steps", []):
            ok, reason = _safe_code(s.get("code", ""))
            if not ok:
                return {"ok": False, "error": "计划含未授权步骤「%s」: %s"
                        % (s.get("name", ""), reason)}
            s = dict(s)
            s.setdefault("status", "pending")
            s.setdefault("output", "")
            steps.append(s)
        task = _new_task(plan_data.get("plan_text", "执行你的指令"), steps)
        task["prompt"] = prompt
        return {"ok": True, "task": _public_task(task)}
    elif op == "execute":
        tid = str(data.get("id", ""))
        with _TASKS_LOCK:
            t = _TASKS.get(tid)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if t["status"] not in ("planned",):
            return {"ok": False, "error": "任务已开始"}
        threading.Thread(target=_worker, args=(tid,), daemon=True).start()
        return {"ok": True, "task": _public_task(t)}
    elif op == "continue":
        # human approved an awaiting_confirm step; release it
        tid = str(data.get("id", ""))
        step_idx = int(data.get("index", -1))
        with _TASKS_LOCK:
            t = _TASKS.get(tid)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if 0 <= step_idx < len(t["steps"]):
            ev = t["steps"][step_idx].get("_event")
            if ev:
                ev.set()
        return {"ok": True, "task": _public_task(t)}
    elif op == "cancel":
        tid = str(data.get("id", ""))
        _cancel_task(tid)
        return {"ok": True}
    elif op == "summarize":
        if not llm_configured():
            return {"ok": False, "error": "LLM 未配置"}
        screens = data.get("screens") or []
        if not screens:
            return {"ok": False, "error": "没有可总结的屏幕文字"}
        try:
            summary = summarize([str(s) for s in screens])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "总结失败: %s" % e}
        return {"ok": True, "summary": summary}

    if op == "tap":
        _require_ready()
        A.tap(int(data["x"]), int(data["y"]))
    elif op == "swipe":
        _require_ready()
        A.swipe(int(data["x1"]), int(data["y1"]),
                int(data["x2"]), int(data["y2"]),
                float(data.get("duration", 0.2)))
    elif op == "long_press":
        _require_ready()
        A.long_press(int(data["x"]), int(data["y"]),
                     float(data.get("duration", 0.8)))
    elif op == "home":
        _require_ready(); A.home()
    elif op == "back":
        _require_ready(); A.back()
    elif op == "keyevent":
        _require_ready(); A.keyevent(str(data["name"]))
    elif op == "type":
        _require_ready(); A.type_text(str(data["text"]))
    elif op == "type_unicode":
        _require_ready(); H.type_unicode(str(data["text"]))
    elif op == "open":
        _require_ready(); H.open_app(str(data["name"]))
    elif op == "launch":
        _require_ready(); A.launch(str(data["pkg"]))
    elif op == "run":
        return _run_script(str(data.get("code", "")))
    elif op == "natural":
        # Natural-language command -> translate to harness code -> safety check
        # -> execute. Outward actions without step_ask are blocked.
        if not llm_configured():
            return {"ok": False, "error": "LLM 未配置：在 .env 设置 LLM_BASE_URL/"
                    "LLM_API_KEY/LLM_MODEL"}
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            return {"ok": False, "error": "空指令"}
        try:
            code = translate(prompt)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "翻译失败: %s" % e}
        ok, reason = _safe_code(code)
        if not ok:
            return {"ok": False, "blocked": True, "code": code,
                    "error": reason}
        # expose task/helpers to the translated code
        result = _run_script_with(code, {"H": H, "A": A, "task": __import__(
            "android_harness.task", fromlist=["task"])})
        result["code"] = code
        result["needs_confirm"] = "step_ask" in code
        return result
    else:
        raise RuntimeError("unknown op %r" % op)
    return {"ok": True}


def _run_script(code):
    g = {k: v for k, v in vars(H).items() if not k.startswith("_")}
    g["__name__"] = "__main__"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, g)
        return {"ok": True, "output": buf.getvalue()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "output": "ERROR: %s: %s" % (type(e).__name__, e)}


def _run_script_with(code, extra):
    """Run translated code with an explicit globals namespace (H, A, task)."""
    g = dict(extra)
    g["__name__"] = "__main__"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, g)
        return {"ok": True, "output": buf.getvalue()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "output": "ERROR: %s: %s" % (type(e).__name__, e)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
            ctype = "application/json"
        data = body.encode("utf-8") if isinstance(body, str) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            # Client closed the connection early (e.g. a proxy dropping the
            # local loopback, or the browser navigating away). This is normal
            # network behaviour, not a server fault — don't dump a traceback.
            pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/control.html"):
            f = WEB_DIR / "control.html"
            if f.exists():
                self._send(200, f.read_text(encoding="utf-8"),
                           "text/html; charset=utf-8")
            else:
                self._send(404, "control.html missing")
            return
        if path == "/state":
            self._send(200, _state())
            return
        if path == "/nodes":
            try:
                _require_ready()
                nodes = H.dump_nodes()
                self._send(200, nodes)
            except Exception as e:  # noqa: BLE001
                self._send(200, {"error": str(e)})
            return
        if path == "/screen":
            try:
                _require_ready()
                p = H.screenshot()
                self._send(200, Path(p).read_bytes(), "image/png")
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/task/"):
            tid = path[len("/task/"):]
            with _TASKS_LOCK:
                t = _TASKS.get(tid)
            self._send(200, _public_task(t) or {"error": "任务不存在"})
            return
        self._send(404, "not found")

    def do_POST(self):
        if self.path.split("?")[0] != "/action":
            self._send(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8", "replace") or "{}")
            op = data.get("op")
            result = _do_action(op, data)
            self._send(200, result)
        except Exception as e:  # noqa: BLE001
            self._send(200, {"ok": False, "error": "%s: %s" %
                             (type(e).__name__, e)})


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(description="android-harness web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = p.parse_args(argv)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d" % (args.host, args.port)
    print("android-harness web UI → %s" % url)
    print("Open that in your browser. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
