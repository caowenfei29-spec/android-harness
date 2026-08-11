"""Diagnostics: `android-harness --doctor` walks the adb/device ladder.
"""
import os
import shutil

from . import adb


def _check(label, ok, hint=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {hint}" if (not ok and hint) else ""))
    return ok


def run_doctor():
    print("android-harness doctor\n")
    ok = True

    # 1) adb binary
    found = adb.ADB
    adb_ok = (found != "adb") or (shutil.which("adb") is not None)
    ok &= _check("adb binary", adb_ok,
                 f"not found at {found}; put platform-tools on PATH or set ADB=")
    if not adb_ok:
        return 1

    # 2) device connected
    state = adb.device_state()
    if state == "ready":
        _check("phone connected (adb device)", True)
    elif state == "offline":
        ok &= _check("phone connected", False,
                     "device is OFFLINE — replug USB / re-authorize USB debugging")
    else:
        ok &= _check("phone connected", False,
                     "no device — plug in phone, enable USB debugging, approve prompt")

    # 3) uiautomator present
    if state == "ready":
        out = adb.run("shell", "which uiautomator", timeout=10,
                      check=False).stdout
        ok &= _check("uiautomator on device", bool(out.strip()),
                     "missing on this ROM")

        # 4) can we dump the UI? (the eyes)
        try:
            path = adb.dump_ui()
            size = os.path.getsize(path)
            ok &= _check(f"UI dump works ({size} bytes)", size > 200,
                         "dump came back empty")
        except Exception as e:  # noqa: BLE001
            ok &= _check("UI dump works", False, str(e)[:120])

        # 5) screen size known
        sz = adb.screen_size()
        _check(f"screen size = {sz}", sz is not None)

    print("\nall clear" if ok else "\nfix the FAILs above, then re-run")
    return 0 if ok else 1
