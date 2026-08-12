"""Device bridge: wraps the proven android_harness.adb module as the executor.

Reuses the battle-tested adb.py (OPPO/ColorOS handling: uiautomator dump 137
retries, monkey fallback for launch, ADBKeyboard unicode input). This is the
`Device` a protocol action executes against.

Device isolation: each AndroidDevice pins its serial via adb.set_serial()
using contextvars, so concurrent tasks on different devices never race (the
old `ADB.SERIAL = serial` assignment was a no-op — ADB is a string, and adb.py
reads a module-level var; see adb.set_serial).
"""
from __future__ import annotations

import json
import sys
import time
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
        # Pin this device for the CURRENT thread/task (contextvars-scoped).
        if serial:
            ADB.set_serial(serial)
        self.d = self  # lightweight probe interface

    # --- perception helpers (used by agent_loop/perception) --------------
    def current_app(self):
        self._pin()
        return ADB.current_app()

    def screen_size(self):
        self._pin()
        return ADB.screen_size()

    def dump_nodes(self):
        self._pin()
        path = ADB.dump_ui()
        return H._ui.parse(path)

    def screenshot(self, path=None):
        self._pin()
        return H.screenshot(path)

    def wait_stable(self, timeout=6.0, interval=0.5, settle=2):
        self._pin()
        return H.wait_stable(timeout=timeout, interval=interval, settle=settle)

    def is_installed(self, package: str) -> bool:
        """Whether the target package is installed on the device."""
        self._pin()
        try:
            out = ADB.run("shell", "pm", "list", "packages", package,
                          timeout=15, check=False).stdout
            return f"package:{package}" in out
        except Exception:  # noqa: BLE001
            return False

    def is_locked(self) -> bool:
        """Heuristic: is the device on the lock screen / keyguard?"""
        self._pin()
        try:
            out = ADB.run("shell", "dumpsys", "window", "policy",
                          timeout=10, check=False).stdout
            return "mShowingLockscreen=true" in out \
                or "isStatusBarKeyguard=true" in out \
                or "mKeyguardShowing=true" in out
        except Exception:  # noqa: BLE001
            return False

    def current_ime(self) -> str:
        self._pin()
        return ADB._current_ime() or ""

    def clipboard(self) -> str:
        """Read clipboard text (best-effort; unreliable across ROMs)."""
        self._pin()
        try:
            out = ADB.run("shell", "cmd", "clipboard", "get-text",
                          timeout=10, check=False).stdout
            return out.strip()
        except Exception:  # noqa: BLE001
            return ""

    def _pin(self):
        """Re-assert the device serial in case a different thread re-targeted
        the shared context in the meantime. Cheap; keeps us isolated."""
        if self.serial:
            ADB.set_serial(self.serial)

    # --- actions ----------------------------------------------------------
    def execute(self, action) -> ExecResult:
        t = action.get("type")
        self._pin()
        try:
            return {
                "get_state": lambda: ExecResult(True, "ok"),
                "launch_app": lambda: self._launch(action),
                "tap": lambda: self._tap(action),
                "long_press": lambda: self._long_press(action),
                "swipe": lambda: self._swipe(action),
                "input_text": lambda: self._input_text(action),
                "set_clipboard": lambda: self._set_clipboard(action),
                "paste": lambda: self._paste(action),
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
        """Type text into the field at (x,y), honoring clear/submit.

        - clear=true  -> clear the field before typing (select-all + delete,
          falling back to repeated KEYCODE_DEL).
        - submit=true -> press ENTER after typing (search / single-field).
        - Unicode (Chinese) uses ADBKeyboard; falls back to `input text`.
        """
        text = str(action.get("text", ""))
        x, y = int(action["x"]), int(action["y"])
        ADB.tap(x, y)
        time.sleep(0.3)
        if action.get("clear"):
            self._clear_field()
        if text:
            try:
                H.type_unicode(text)
            except Exception:  # noqa: BLE001
                ADB.type_text(text)
        if action.get("submit"):
            ADB.keyevent("KEYCODE_ENTER")
            time.sleep(0.3)
        return ExecResult(True, f"typed into ({x},{y})")

    def _clear_field(self):
        """Select-all then delete; fall back to repeated KEYCODE_DEL."""
        try:
            # Select all then backspace — clears the whole field in one shot.
            ADB.keyevent("KEYCODE_MOVE_END")
            ADB.keyevent("KEYCODE_DEL")  # may not select-all on all ROMs
            ADB.keyevent("KEYCODE_A")    # Ctrl+A select-all
        except Exception:  # noqa: BLE001
            pass
        # Belt-and-braces: a handful of DEL presses for short leftovers.
        for _ in range(5):
            ADB.keyevent("KEYCODE_DEL")
        time.sleep(0.2)

    def _set_clipboard(self, action):
        """Put text on the clipboard. Prefers the ADBKeyboard broadcast (works
        on ColorOS where `cmd clipboard set-text` returns nothing), falls back
        to `cmd clipboard set-text`."""
        text = str(action.get("text", ""))
        try:
            safe = text.replace("'", "'\\''")
            ADB.run("shell",
                    f"am broadcast -a ADB_SET_CLIPBOARD --es msg '{safe}'",
                    timeout=10, check=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            ADB.run("shell", f"cmd clipboard set-text '{text}'",
                    timeout=10, check=False)
        except Exception:  # noqa: BLE001
            pass
        return ExecResult(True, "clipboard set")

    def _paste(self, action):
        """Long-press the field at (x,y) to bring up the paste menu, then tap
        the paste option — the paste-first flow for messaging."""
        x, y = int(action["x"]), int(action["y"])
        ADB.long_press(x, y, 0.8)
        time.sleep(0.6)
        # Try to find and tap the "paste" menu item in the UI tree.
        try:
            path = ADB.dump_ui()
            nodes = H._ui.parse(path)
            for n in nodes:
                label = (n.get("text") or n.get("desc") or "").strip()
                if label in ("粘贴", "Paste"):
                    ADB.tap(n["x"], n["y"])
                    return ExecResult(True, "pasted")
        except Exception:  # noqa: BLE001
            pass
        return ExecResult(False, "paste menu not found")

    def _back(self):
        ADB.back()
        return ExecResult(True, "back")

    def _home(self):
        ADB.home()
        return ExecResult(True, "home")

    def _wait(self, action):
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
        r = ExecResult(True, "clipboard")
        r.data = {"text": self.clipboard()}
        return r
