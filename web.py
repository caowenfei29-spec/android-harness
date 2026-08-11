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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS_ROOT / "src"))

from android_harness import helpers as H  # noqa: E402
from android_harness import adb as A      # noqa: E402
from android_harness import ui as UI       # noqa: E402

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


def _do_action(op, data):
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
            ctype = "application/json"
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
        self._send(404, "not found")

    def do_POST(self):
        if self.path.split("?")[0] != "/action":
            self._send(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
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
