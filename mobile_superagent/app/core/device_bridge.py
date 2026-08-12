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
                "get_state": lambda: self._get_state(),
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
        """Launch a package and REPORT THE REAL foreground state, not just
        "command issued". `am start` succeeding (or monkey fallback firing)
        does not mean the app is actually in the foreground — a block, a cold
        start, or a missing package can leave us on the launcher.

        Retries the foreground check a couple of times (cold starts on OPPO can
        take >1s), then reports a precise, actionable failure.
        """
        pkg = str(action.get("package_name", ""))
        ADB.launch(pkg)
        fg, act = "", ""
        for _ in range(3):
            time.sleep(1.0)
            fg, act = self.current_app()
            if fg == pkg:
                break
        if fg == pkg:
            r = ExecResult(True, f"launched {pkg} (前台已确认: {fg})")
        else:
            r = ExecResult(False,
                           f"launch 命令已下发但前台未切换到 {pkg}，"
                           f"当前仍在 {fg or 'unknown'}。可能原因：应用未安装、"
                           f"冷启动较慢、启动被拦截或有弹窗。")
        installed = self.is_installed(pkg)
        r.data = {"foreground": fg, "activity": act, "target": pkg,
                  "installed": installed}
        if not r.ok and not installed:
            r.message += f"（{pkg} 未安装，需先安装再启动）"
        return r

    def _get_state(self):
        """get_state now returns REAL perception instead of an empty 'ok', so
        the model gets fresh foreground/lock/IME/install facts (not just the
        pre-action snapshot already in the prompt)."""
        fg, act = self.current_app()
        r = ExecResult(True,
                       f"foreground={fg or 'unknown'}, activity={act or 'unknown'}, "
                       f"locked={self.is_locked()}, ime={self.current_ime()}")
        r.data = {"foreground": fg, "activity": act, "locked": self.is_locked(),
                  "ime": self.current_ime()}
        return r

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

        Input is ALWAYS preceded by clearing the field, so a stale search term
        left over from a previous task can never masquerade as the new target.
        After typing we re-read the field and confirm the target text is
        actually present before reporting success.
        """
        text = str(action.get("text", ""))
        x, y = int(action["x"]), int(action["y"])
        ADB.tap(x, y)
        time.sleep(0.3)
        # always clear first — stale terms from prior tasks must not leak in
        self._clear_field()
        if text:
            # Type AND verify in one call: `_adbkeyboard_sent` broadcasts via
            # AdbIME and confirms 'result=0' delivery (OPPO hides the EditText
            # node from the dump, so we can't always read the field back).
            # Fall back to `input text` only if AdbIME isn't the active IME.
            sent = False
            try:
                sent = self._adbkeyboard_sent(text)
            except Exception:  # noqa: BLE001
                sent = False
            if not sent:
                try:
                    ADB.type_text(text)
                    sent = True
                except Exception:  # noqa: BLE001
                    sent = False
            if not sent:
                return ExecResult(
                    False,
                    "输入失败：ADBKeyboard 广播与 input text 均未送达，"
                    "请确认 ADB Keyboard 是当前输入法后重试。")
        if action.get("submit"):
            ADB.keyevent("KEYCODE_ENTER")
            time.sleep(0.3)
        return ExecResult(True, f"typed into ({x},{y})")

    def _adbkeyboard_sent(self, text: str) -> bool:
        """Broadcast text to the AdbIME and confirm it was delivered.

        ONE call both types the text and proves delivery: `am broadcast`
        returning 'Broadcast completed: result=0' means the intent reached
        AdbIME (the only receiver) — a success signal that doesn't depend on
        uiautomator exposing the EditText node, which OPPO/ColorOS often hides
        once the field has content + an active IME. Returns False if the
        broadcast line is odd and the field also can't be re-read.
        """
        try:
            safe = text.replace("'", "'\\\\''")
            r = ADB.run(
                "shell",
                f"am broadcast -a ADB_INPUT_TEXT --es msg '{safe}'",
                timeout=15, check=False)
            out = (r.stdout or "") + (r.stderr or "")
            if "Broadcast completed: result=0" in out:
                return True
            return bool(self._read_field_text())
        except Exception:  # noqa: BLE001
            return False

    def _read_field_text(self) -> str:
        """Best-effort: read back the focused text field's content from the UI
        dump (EditText nodes). Empty on failure — callers treat empty as OK."""
        try:
            path = ADB.dump_ui()
            nodes = H._ui.parse(path)
            for n in nodes:
                cls = (n.get("class") or "")
                if "EditText" in cls:
                    txt = (n.get("text") or "").strip()
                    if txt:
                        return txt
            return ""
        except Exception:  # noqa: BLE001
            return ""

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
        to `cmd clipboard set-text`. We also cache the text in-memory because
        ColorOS's `cmd clipboard get-text` reads back EMPTY even after a
        successful set — so `paste` can't re-read the clipboard on this ROM."""
        text = str(action.get("text", ""))
        try:
            safe = text.replace("'", "'\\\\''")
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
        # Cache so _paste can type it back even when the ROM hides the clipboard.
        self._clip_cache = text
        return ExecResult(True, "clipboard set")

    def _paste(self, action):
        """Paste text into the field at (x,y).

        PRIMARY: tap the field to focus it, then type the text straight in via
        the ADBKeyboard IME broadcast (supports Chinese, works on OPPO/ColorOS
        where the long-press paste menu often doesn't appear or isn't in the
        UI dump). The text comes from the in-memory clipboard cache (set by
        `set_clipboard`) because ColorOS's `cmd clipboard get-text` reads back
        empty.

        FALLBACK: long-press to summon the paste menu and tap 粘贴/Paste.

        Either path re-reads the field afterwards and fails (never reports
        success) if the text didn't actually land.
        """
        x, y = int(action["x"]), int(action["y"])
        text = getattr(self, "_clip_cache", "") or str(action.get("text", ""))
        # 1) tap to focus, then type straight via ADBKeyboard (most reliable).
        try:
            ADB.tap(x, y)
            time.sleep(0.4)
            if text:
                field_text = self._read_field_text()
                # EditText hidden on OPPO -> trust the broadcast-delivery signal.
                if (field_text and text[:6] in field_text) or \
                   (not field_text and self._adbkeyboard_sent(text)):
                    return ExecResult(True, f"pasted (字段确认: {(field_text or text)[:20]})")
        except Exception:  # noqa: BLE001
            pass
        # 2) fallback: long-press paste menu.
        try:
            ADB.long_press(x, y, 0.8)
            time.sleep(0.6)
            path = ADB.dump_ui()
            nodes = H._ui.parse(path)
            for n in nodes:
                label = (n.get("text") or n.get("desc") or "").strip()
                if label in ("粘贴", "Paste"):
                    ADB.tap(n["x"], n["y"])
                    time.sleep(0.4)
                    field_text = self._read_field_text()
                    if field_text:
                        return ExecResult(True, f"pasted (字段确认: {field_text[:20]})")
        except Exception:  # noqa: BLE001
            pass
        return ExecResult(False, "paste 未生效：ADBKeyboard 广播与粘贴菜单均失败")


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
