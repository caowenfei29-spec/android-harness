"""ADB transport for android-harness.

The thin layer between the agent and the phone:
  - runs adb shell commands (the "hands")
  - dumps the UI hierarchy via uiautomator (the "eyes" — a real DOM,
    not OCR; every node carries its own screen-point bounds)

Coordinates are device pixels throughout. Android input uses device px
and the uiautomator dump reports device px, so no scaling is needed.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

# --- adb binary discovery -------------------------------------------------

_CANDIDATES = [
    os.environ.get("ADB"),
    "adb",
    "/d/AndroidTools/platform-tools/adb.exe",
    "/d/AndroidDev/sdk/platform-tools/adb.exe",
    "D:/AndroidTools/platform-tools/adb.exe",
    "D:/AndroidDev/sdk/platform-tools/adb.exe",
    str(Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"),
]


def _find_adb():
    for c in _CANDIDATES:
        if not c:
            continue
        if c == "adb":
            found = shutil.which("adb")
            if found:
                return found
            continue
        if Path(c).exists():
            return c
    return "adb"  # last resort; will fail loudly if truly missing


ADB = _find_adb()
SERIAL = os.environ.get("ANDROID_SERIAL")  # optional: target a specific device


# --- low-level run --------------------------------------------------------

def _argv(*args):
    base = [ADB]
    if SERIAL:
        base += ["-s", SERIAL]
    return base + list(args)


def run(*args, timeout=30, check=True, capture=True):
    """Run an adb command; return subprocess.CompletedProcess-like dict."""
    argv = _argv(*args)
    try:
        cp = subprocess.run(
            argv,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"adb not found at {ADB}. Install platform-tools and put adb on "
            f"PATH, or set ADB=/path/to/adb.exe")
    if check and cp.returncode != 0:
        raise RuntimeError(
            f"adb failed ({cp.returncode}): {' '.join(argv)}\n"
            f"{cp.stderr.strip() or cp.stdout.strip()}")
    return cp


def shell(cmd, timeout=30, check=True):
    """Run `adb shell <cmd>` and return stdout."""
    cp = run("shell", cmd, timeout=timeout, check=check)
    return cp.stdout


# --- connection state -----------------------------------------------------

def device_state():
    """'ready' | 'no-device' | 'offline'.

    Connecting the phone is the USER's job (plug in, enable USB debugging,
    approve the prompt). The harness never connects for you.
    """
    cp = run("get-state", timeout=10, check=False, capture=True)
    if cp.returncode != 0:
        return "no-device"
    out = cp.stdout.strip()
    if out == "device":
        return "ready"
    if out == "offline":
        return "offline"
    return "no-device"


def ensure_device():
    """Raise with a user-facing message if no phone is connected. STOP and
    relay that message; do not try to reconnect."""
    state = device_state()
    if state == "ready":
        return
    if state == "offline":
        raise RuntimeError(
            "Phone is connected but OFFLINE. Please unplug/replug the USB "
            "cable, or revoke & re-authorize USB debugging in Developer "
            "Options, then retry. I cannot fix this for you.")
    raise RuntimeError(
        "No Android phone is connected via ADB. Please: plug the phone in "
        "over USB, enable 'USB debugging' in Developer Options, and approve "
        "the authorization prompt on the phone — then retry. Connecting is a "
        "physical action only you can do; I will not try to connect it.")


# --- input primitives (the hands) ----------------------------------------

def tap(x, y):
    run("shell", "input", "tap", str(x), str(y), timeout=15)
    time.sleep(0.15)


def long_press(x, y, duration=0.8):
    # input swipe with no movement = long press
    run("shell", "input", "swipe", str(x), str(y), str(x), str(y),
        str(int(duration * 1000)), timeout=15)
    time.sleep(0.1)


def swipe(x1, y1, x2, y2, duration=0.2):
    run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2),
        str(int(duration * 1000)), timeout=15)
    time.sleep(0.1)


def drag(x1, y1, x2, y2, duration=0.35):
    swipe(x1, y1, x2, y2, duration)


def keyevent(name):
    run("shell", "input", "keyevent", name, timeout=15)
    time.sleep(0.1)


def type_text(text):
    """Type ASCII via `input text`. Chinese/unicode needs ADBKeyboard — see
    type_unicode(). Raises on characters input cannot send."""
    # input text takes a single-quoted shell arg; spaces become spaces.
    # Some shells mangle it, so pass through a temp-safe quoting:
    safe = text.replace("'", "'\\''")
    run("shell", f"input text '{safe}'", timeout=15)
    time.sleep(0.1)


_IME_ADB = "com.android.adbkeyboard/.AdbIME"


def _current_ime():
    out = run("shell", "settings get secure default_input_method",
              timeout=10, check=False).stdout
    return out.strip()


def type_unicode(text):
    """Type arbitrary unicode (incl. Chinese) via ADBKeyboard broadcast.

    ADBKeyboard must be the ACTIVE input method for the broadcast to land;
    select it once in phone Settings (键盘与输入法 → 当前输入法 → ADB Keyboard).
    On ColorOS/Oppo, `adb shell ime set` is blocked (WRITE_SECURE_SETTINGS
    revoked from adb shell), so the harness can't auto-switch the keyboard —
    it broadcasts directly and verifies beforehand, raising clear steps if
    ADBKeyboard isn't the active IME.
    """
    if not adbkeyboard_installed():
        raise RuntimeError(
            "ADBKeyboard 未安装。请先安装 vendor/ADBKeyboard.apk，再在手机设置里"
            "把 ADB Keyboard 设为当前输入法，然后 type_unicode() 即可打中文。")
    cur = _current_ime()
    if _IME_ADB not in (cur or ""):
        raise RuntimeError(
            "ADBKeyboard 已安装，但当前输入法不是它，adb 也无法自动切换"
            "（ColorOS 限制了 WRITE_SECURE_SETTINGS）。\n"
            "请在手机上手动切换：设置 → 其他设置 → 键盘与输入法 → 当前输入法 "
            "→ 选择 ADB Keyboard。选好后 type_unicode() 即可打中文；用完了在同一"
            "菜单切回 搜狗 即可。")
    # msg is wrapped in single quotes for the device-side shell. Escape
    # embedded single quotes so an odd/malicious msg cannot break out of the
    # quotes and inject extra shell commands (prompt-injection -> RCE surface).
    safe = text.replace("'", "'\\''")
    run("shell",
        f"am broadcast -a ADB_INPUT_TEXT --es msg '{safe}'",
        timeout=15)
    time.sleep(0.3)


def adbkeyboard_installed():
    out = run("shell", "pm list packages", timeout=15, check=False).stdout
    return "com.android.adbkeyboard" in out


def install_adbkeyboard():
    """Attempt to enable ADBKeyboard. The APK must already be on the host;
    we don't bundle one. Returns a human message of what to do."""
    # No bundled APK — point the user to install.md.
    raise RuntimeError(
        "android-harness does not bundle ADBKeyboard. Install it once:\n"
        "  1) download ADBKeyboard.apk (e.g. from the F-Droid/GitHub source)\n"
        "  2) `adb install ADBKeyboard.apk`\n"
        "  3) on the phone: Settings > Language & input > Current keyboard > "
        "add ADBKeyboard and select it\n"
        "Then type_unicode() works for Chinese. (See install.md.)")


def screen_size():
    out = shell("wm size", timeout=10)
    m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def current_app():
    out = shell("dumpsys window", timeout=10)
    m = re.search(r"mCurrentFocus=Window\{[^ ]+ \w+ ([^/]+)/([^} ]+)", out)
    if m:
        return m.group(1), m.group(2)
    return None, None


# --- UI dump (the eyes) ---------------------------------------------------

_DUMP_REMOTE = "/sdcard/android-harness-ui.xml"
_TMP = Path(tempfile.gettempdir()) / "android-harness"
_TMP.mkdir(exist_ok=True)


def dump_ui(pull=True):
    """Dump the UI hierarchy to a local XML file and return its path.

    Uses `uiautomator dump`. The resulting XML is the real view tree —
    every node has text, content-desc, class, and bounds. This is the
    element tree, far more reliable than OCR.

    ColorOS occasionally kills uiautomator (exit 137); retry a few times.
    """
    last = None
    for attempt in range(4):
        try:
            run("shell", f"uiautomator dump {_DUMP_REMOTE} >/dev/null 2>&1",
                timeout=20, check=True)
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0)
    else:
        raise RuntimeError(f"uiautomator dump failed after retries: {last}")
    local = _TMP / "ui.xml"
    run("pull", _DUMP_REMOTE, str(local), timeout=20)
    return str(local)


def launch(pkg, activity=None):
    """Launch an app by package (and optional activity) via `am start`."""
    if activity:
        run("shell", "am", "start", "-n", f"{pkg}/{activity}", timeout=15)
    else:
        run("shell", "am", "start", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", "-p", pkg, timeout=15)
    time.sleep(1.0)


def home():
    keyevent("KEYCODE_HOME")


def back():
    keyevent("KEYCODE_BACK")
