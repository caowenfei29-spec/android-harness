"""
Agent-editable android helpers.

Add trusted task-specific primitives here. This file is loaded only by the
explicit ``android-harness --unsafe-script`` compatibility mode; the JSON
planner, policy engine, and safe executor never import it.

ColorOS / OPPO R17 notes:
- ADBKeyboard is installed and *enabled*, but ColorOS blocks `adb shell ime set`
  (WRITE_SECURE_SETTINGS revoked from adb shell), so the harness cannot
  auto-switch the keyboard. Select "ADB Keyboard" as the current input method
  once in: 设置 → 其他设置 → 键盘与输入法 → 当前输入法 → ADB Keyboard.
  After that, type_unicode("中文") types Chinese into a focused text field;
  switch back to 搜狗 in the same menu when done (does not affect daily typing).
- `uiautomator dump` occasionally dies (exit 137) on ColorOS — dump_ui() already
  retries. If a read still fails, just re-run the step.
"""
