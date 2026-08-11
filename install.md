# android-harness install

Use once. For phone work, read `SKILL.md`.

## Requirements

- A phone with **USB debugging** enabled (Settings > About > tap Build number
  7× to unlock Developer Options; then Developer Options > USB debugging).
- `adb` (Android platform-tools) on your PATH, or set `ADB=/path/to/adb.exe`.
- Python 3.10+ (standard library only — no pip installs needed).
- The phone connected over USB and authorized.

## Fast Path

```bash
git clone <this-repo> D:/AndroidTools/android-harness
cd D:/AndroidTools/android-harness

# optional: install as a global command (editable, stays at this path)
pip install -e . --no-deps

# or just use the dev launcher (no install needed):
./android-harness --doctor

# register as a skill so Claude Code / Codex auto-use it
mkdir -p ~/.claude/skills/android-harness
./android-harness skill > ~/.claude/skills/android-harness/SKILL.md
```

If `--doctor` prints `all clear`, you're done.

`D:/AndroidTools/android-harness` is the canonical home (D: drive, portable).
The code, `agent_helpers.py`, `SKILL.md`, and `agent-workspace/` always live
there. `pip install -e .` binds the `android-harness` command to that source;
keep the folder there or re-run `pip install -e .` if you move it.

## Connecting the phone (the user's job)

1. Enable USB debugging on the phone.
2. Plug in over USB.
3. On the phone, approve the "Allow USB debugging?" prompt (check "always").
4. `android-harness --doctor` should now show `phone connected (adb device)`.

If it shows `offline`: unplug/replug, or revoke USB debugging authorizations in
Developer Options and approve again.

## Typing Chinese / unicode (optional)

`type_text()` only sends ASCII. For Chinese, install **ADBKeyboard**:

```bash
# the APK is already bundled with this repo (vendor/ADBKeyboard.apk)
adb install -r vendor/ADBKeyboard.apk
```

Then on the phone: **Settings → 语言与输入法/键盘与输入法 → 当前键盘 → 选择
ADBKeyboard** (one-time). After that, `type_unicode("中文")` works in scripts.

> **ColorOS / OPPO note:** `adb shell ime set` is blocked (WRITE_SECURE_SETTINGS
> revoked from adb shell), so the harness can't auto-switch the keyboard for
> you. ADBKeyboard must be selected manually once as above. The harness detects
> this and prints clear steps instead of failing silently. Once selected,
> switch back to 搜狗 in the same menu when you're done.
>
> One-time selection path that works on OPPO R17: 设置 → 其他设置 →
> 键盘与输入法 → 当前输入法 → 选择 **ADB Keyboard**.

## Visual control page (local)

A browser-based remote control UI is included — live screenshot, click-to-tap,
tap-by-label, type (ASCII / Chinese), home/back, open app, and a Python script
console. The server binds to **127.0.0.1 only** (not exposed to the network).

```bash
# run it (any of these)
python web.py                          # dev launcher
python -m android_harness.run web      # via installed command
# then open:
start http://127.0.0.1:8741
```

Features in the page:
- Click anywhere on the mirrored screen to tap that coordinate.
- Toggle "显示控件" to overlay tappable UI boxes (from the real view tree).
- "按文字点击" chips: tap a labeled control by name.
- Script console: run real `android_harness.helpers` Python against the phone.

## --doctor ladder

`--doctor` walks: adb binary → phone connected → uiautomator present → UI dump
works → screen size known. Fix the first FAIL; later checks depend on it.

Common cases:
- **phone connected = FAIL**: USB debugging off, cable is charge-only, or the
  prompt wasn't approved.
- **UI dump works = FAIL**: a system dialog (permission popup, keyboard) is
  covering the screen — dismiss it and retry.
- **uiautomator missing**: rare on stock ROMs; some heavily customized launchers
  hide it. A fallback `dumpsys` parser can be added if needed.
