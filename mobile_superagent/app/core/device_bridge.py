"""Device bridge: wraps the proven android_harness.adb module as the executor.

Reuses the battle-tested adb.py (OPPO/ColorOS handling: uiautomator dump 137
retries, monkey fallback for launch, ADBKeyboard unicode input). This is the
`Device` a protocol action executes against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..settings import settings


def _load_harness():
    """Import the shared android_harness.adb + helpers from the repo root."""
    sys.path.insert(0, settings.harness_pkg_root)
    from android_harness import adb  # noqa: F401
    from android_harness import helpers  # noqa: F401
    return adb, helpers


ADB, H = _load_harness()


class ExecResult:
    def __init__(self, ok: bool, message: str = ""):
        self.ok = ok
        self.message = message
        self.data = {}

    def __dict__(self):  # serialization helper
        return {"ok": self.ok, "message": self.message, "data": self.data}


class AndroidDevice:
    def __init__(self, serial: str | None = None):
        self.serial = serial
        if serial:
            ADB.SERIAL = serial
        self.d = self  # lightweight probe interface

    # --- perception helpers (used by agent_loop/perception) --------------
    def current_app(self):
        return ADB.current_app()

    def screen_size(self):
        return ADB.screen_size()

    def dump_nodes(self):
        path = ADB.dump_ui()
        return H._ui.parse(path)

    def screenshot(self, path=None):
        return H.screenshot(path)

    # --- actions ----------------------------------------------------------
    def execute(self, action) -> ExecResult:
        t = action.get("type")
        try:
            return {
                "get_state": lambda: ExecResult(True, "ok"),
                "launch_app": lambda: self._launch(action),
                "tap": lambda: self._tap(action),
                "long_press": lambda: self._long_press(action),
                "swipe": lambda: self._swipe(action),
                "input_text": lambda: self._input_text(action),
                "back": lambda: self._back(),
                "home": lambda: self._home(),
                "wait": lambda: self._wait(action),
                "open_url": lambda: self._open_url(action),
                "play_store_search": lambda: self._play_store(action),
                "uninstall_app": lambda: self._uninstall(action),
                "get_clipboard": lambda: self._clipboard(),
                "request_user_takeover": lambda: ExecResult(True, "takeover"),
                "respond_to_user": lambda: ExecResult(True, "respond"),
            }.get(t, lambda: ExecResult(False, f"unknown action {t}"))()
        except Exception as e:  # noqa: BLE001
            return ExecResult(False, f"{type(e).__name__}: {e}")

    # --- individual executors ---------------------------------------------
    def _launch(self, action):
        ADB.launch(str(action.get("package_name", "")))
        return ExecResult(True, f"launched {action.get('package_name')}")

    def _tap(self, action):
        ADB.tap(int(action["x"]), int(action["y"]))
        return ExecResult(True, f"tapped ({action['x']},{action['y']})")

    def _long_press(self, action):
        ADB.long_press(int(action["x"]), int(action["y"]),
                       float(action.get("duration_ms", 800)) / 1000.0)
        return ExecResult(True, f"long-pressed ({action['x']},{action['y']})")

    def _swipe(self, action):
        ADB.swipe(int(action["x1"]), int(action["y1"]),
                  int(action["x2"]), int(action["y2"]),
                  float(action.get("duration_ms", 400)) / 1000.0)
        return ExecResult(True, "swiped")

    def _input_text(self, action):
        text = str(action.get("text", ""))
        if not text:
            return ExecResult(False, "input_text 的 text 不能为空")
        ADB.tap(int(action["x"]), int(action["y"]))
        try:
            H.type_unicode(text)
        except Exception:  # noqa: BLE001
            ADB.type_text(text)
        return ExecResult(True, f"typed into ({action['x']},{action['y']})")

    def _back(self):
        ADB.back()
        return ExecResult(True, "back")

    def _home(self):
        ADB.home()
        return ExecResult(True, "home")

    def _wait(self, action):
        import time
        time.sleep(float(action.get("seconds", 3)))
        return ExecResult(True, f"waited {action.get('seconds')}s")

    def _open_url(self, action):
        url = str(action.get("url", ""))
        ADB.run("shell", "am", "start", "-a", "android.intent.action.VIEW",
                "-d", url, timeout=15)
        return ExecResult(True, "opened url")

    def _play_store(self, action):
        # launch Play Store search
        ADB.run("shell", "am", "start", "-a", "android.intent.action.VIEW",
                "-d", "market://search?q=" + str(action.get("app_name", "")),
                timeout=15)
        return ExecResult(True, "play store search")

    def _uninstall(self, action):
        ADB.run("shell", "pm", "uninstall",
                str(action.get("package_name", "")), timeout=30)
        return ExecResult(True, "uninstalled")

    def _clipboard(self):
        out = ADB.run("shell", "clipboard", timeout=10, check=False).stdout
        r = ExecResult(True, "clipboard")
        r.data = {"text": out.strip()}
        return r
