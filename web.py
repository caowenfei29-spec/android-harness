#!/usr/bin/env python3
"""Loopback-only web UI backed by the policy-driven JSON executor."""
from __future__ import annotations

import argparse
import contextlib
import io
import ipaddress
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

HARNESS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_ROOT / "src"))

from android_harness import adb as A  # noqa: E402
from android_harness import helpers as H  # noqa: E402
from android_harness.executor import Executor  # noqa: E402
from android_harness.llm import (  # noqa: E402
    configured as llm_configured,
    generate_plan,
    summarize,
)
from android_harness.plan import TaskPlan  # noqa: E402
from android_harness.policy import (  # noqa: E402
    AuthorizationError,
    ConfirmationRequest,
    PolicyEngine,
)

WEB_DIR = HARNESS_ROOT / "web"
DEFAULT_PORT = int(os.environ.get("ANDROID_HARNESS_WEB_PORT", "8741"))
_UNSAFE_SCRIPT_ENABLED = False


def _state() -> dict[str, Any]:
    state = A.device_state()
    base = {"state": state, "size": None, "package": None,
            "activity": None, "adbkeyboard": False,
            "unsafe_script": _UNSAFE_SCRIPT_ENABLED}
    if state != "ready":
        return base
    size = A.screen_size()
    package, activity = A.current_app()
    return {**base, "size": list(size) if size else None,
            "package": package, "activity": activity,
            "adbkeyboard": A.adbkeyboard_installed()}


def _require_ready() -> None:
    state = A.device_state()
    if state != "ready":
        raise RuntimeError(
            f"Phone not connected (state={state}). Plug in USB, enable USB "
            "debugging, approve the prompt, then retry.")


def _execute_plan(plan: TaskPlan, confirmed: bool) -> dict[str, Any]:
    policy = PolicyEngine()

    def browser_confirmation(_request: ConfirmationRequest) -> bool:
        # The server only accepts loopback clients.  `confirmed` is set after
        # the local UI displays the exact plan and the user accepts it.
        return confirmed is True

    try:
        authorization = policy.authorize(
            plan, confirmer=browser_confirmation if confirmed else None)
    except AuthorizationError as exc:
        return {"ok": False, "confirmation_required": True,
                "plan": plan.to_dict(), "error": str(exc)}
    _require_ready()
    result = Executor(policy=policy, helpers=H).execute(plan, authorization)
    payload = result.to_dict()
    payload["ok"] = result.done
    payload["plan"] = plan.to_dict()
    if not result.done:
        payload["error"] = result.reason
    return payload


def _do_action(op: Any, data: dict[str, Any]) -> dict[str, Any]:
    confirmed = data.get("confirmed") is True
    if op == "natural":
        if not llm_configured():
            return {"ok": False, "error": "LLM 未配置：请设置 LLM_* 环境变量"}
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            return {"ok": False, "error": "空指令"}
        try:
            return _execute_plan(generate_plan(prompt), confirmed)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"计划生成失败: {exc}"}
    if op == "summarize":
        screens = data.get("screens") or []
        if not llm_configured():
            return {"ok": False, "error": "LLM 未配置"}
        if not isinstance(screens, list) or not screens:
            return {"ok": False, "error": "没有可总结的屏幕文字"}
        try:
            return {"ok": True, "summary": summarize([str(x) for x in screens])}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"总结失败: {exc}"}
    if op == "run":
        if not _UNSAFE_SCRIPT_ENABLED:
            return {"ok": False, "blocked": True,
                    "error": "Python console is disabled. Restart the loopback "
                             "server with --unsafe to enable unrestricted code."}
        return _run_unsafe_script(str(data.get("code", "")))

    builders = {
        "tap": lambda: {"type": "tap_coordinates", "x": data["x"], "y": data["y"]},
        "swipe": lambda: {"type": "swipe_coordinates", "x1": data["x1"],
                           "y1": data["y1"], "x2": data["x2"], "y2": data["y2"],
                           "duration": data.get("duration", 0.2)},
        "long_press": lambda: {"type": "long_press", "x": data["x"], "y": data["y"],
                                "duration": data.get("duration", 0.8)},
        "home": lambda: {"type": "home"},
        "back": lambda: {"type": "back"},
        "type": lambda: {"type": "type_text", "text": data["text"]},
        "type_unicode": lambda: {"type": "type_unicode", "text": data["text"]},
        "open": lambda: {"type": "open_app", "target": data["name"]},
        "launch": lambda: {"type": "open_app", "target": data["pkg"]},
    }
    if op == "keyevent":
        name = str(data.get("name", ""))
        if name not in {"KEYCODE_HOME", "KEYCODE_BACK"}:
            return {"ok": False, "blocked": True,
                    "error": "arbitrary keyevents are not in the safe executor"}
        op = "home" if name == "KEYCODE_HOME" else "back"
    try:
        step = builders[str(op)]()
    except KeyError as exc:
        raise RuntimeError(f"unknown op {op!r}") from exc
    return _execute_plan(TaskPlan.from_dict({"version": 1, "steps": [step]}), confirmed)


def _run_unsafe_script(code: str) -> dict[str, Any]:
    namespace = {key: value for key, value in vars(H).items()
                 if not key.startswith("_")}
    namespace["__name__"] = "__main__"
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(compile(code, "<web-unsafe-console>", "exec"), namespace)
        return {"ok": True, "output": output.getvalue()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "output": output.getvalue()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        pass

    def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=_json_default)
            ctype = "application/json"
        payload = body.encode("utf-8") if isinstance(body, str) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; "
                             "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        if not _host_header_allowed(self.headers.get("Host", "")):
            self._send(403, {"error": "non-loopback Host header rejected"})
            return
        path = self.path.split("?")[0]
        if path in {"/", "/control.html"}:
            page = WEB_DIR / "control.html"
            self._send(200, page.read_text(encoding="utf-8"),
                       "text/html; charset=utf-8")
        elif path == "/state":
            self._send(200, _state())
        elif path == "/nodes":
            try:
                _require_ready()
                self._send(200, H.dump_nodes())
            except Exception as exc:  # noqa: BLE001
                self._send(200, {"error": str(exc)})
        elif path == "/screen":
            try:
                _require_ready()
                self._send(200, Path(H.screenshot()).read_bytes(), "image/png")
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"error": str(exc)})
        else:
            self._send(404, "not found")

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/action":
            self._send(404, "not found")
            return
        if not _host_header_allowed(self.headers.get("Host", "")):
            self._send(403, {"ok": False,
                             "error": "non-loopback Host header rejected"})
            return
        if not _origin_allowed(
                self.headers.get("Origin"), self.headers.get("Host", "")):
            self._send(403, {"ok": False,
                             "error": "cross-origin request rejected"})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            self._send(415, {"ok": False,
                             "error": "Content-Type must be application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 1_000_000:
                raise ValueError("request body too large")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8", "strict"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            self._send(200, _do_action(data.get("op"), data))
        except Exception as exc:  # noqa: BLE001
            self._send(200, {"ok": False,
                             "error": f"{type(exc).__name__}: {exc}"})


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_header_allowed(value: str) -> bool:
    """Reject DNS-rebinding Host headers before serving local capabilities."""
    try:
        hostname = urlsplit("//" + value).hostname
    except ValueError:
        return False
    return bool(hostname and _is_loopback(hostname))


def _origin_allowed(value: str | None, expected_host: str | None = None) -> bool:
    """Allow same-machine browser origins and non-browser clients only."""
    if value is None:
        return True
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme != "http" or not hostname or not _is_loopback(hostname):
        return False
    if expected_host is not None:
        try:
            expected = urlsplit("//" + expected_host).netloc.lower()
        except ValueError:
            return False
        return parsed.netloc.lower() == expected
    return True


def main(argv: list[str] | None = None) -> None:
    global _UNSAFE_SCRIPT_ENABLED
    parser = argparse.ArgumentParser(description="android-harness web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--unsafe", action="store_true",
        help="enable unrestricted Python console (loopback hosts only)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not _is_loopback(args.host):
        raise SystemExit(
            "SECURITY ERROR: the web UI may bind only to localhost/loopback addresses")
    _UNSAFE_SCRIPT_ENABLED = bool(args.unsafe)
    if _UNSAFE_SCRIPT_ENABLED:
        print("!" * 72, file=sys.stderr)
        print("WARNING: --unsafe enables unrestricted host Python execution.",
              file=sys.stderr)
        print("Use only with trusted code on this local machine.", file=sys.stderr)
        print("!" * 72, file=sys.stderr)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"android-harness web UI → http://{args.host}:{args.port}")
    print("Python console: " + ("UNSAFE ENABLED" if args.unsafe else "disabled"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
