---
name: android-harness
description: "Control the user's Android phone via ADB: open apps, tap, type, swipe, read the screen through the real UI hierarchy."
---

# android-harness

Direct Android phone control via ADB — the uiautomator UI hierarchy for eyes
(real DOM, not OCR), `input` events for hands. For task-specific edits, use
`agent-workspace/agent_helpers.py`. For setup or connection problems, read
`install.md`.

## When Not to Use

If the task is doable on the Mac/PC or the web — a website, an API, an app with
a web equivalent — do it there and leave the phone alone. Use android-harness
only when the task genuinely needs the phone: Android-only apps, things tied to
the user's number/2FA, checking how something looks on the phone.

## Usage

```bash
android-harness plan "Open 微信" > plan.json
android-harness execute plan.json
```

- `plan` emits JSON and never executes model output.
- `execute` accepts only a strict JSON Task Plan. Use `--confirm` with a plan
  file when risky steps are intentional and have been reviewed.
- `--unsafe-script` is the explicit legacy escape hatch for trusted Python;
  it bypasses policy and prints a warning.
- `ensure_device()` gates every task on the phone being connected.

## Screen Workflow

The helper calls below are the trusted programmatic API used by Executor and
explicit unsafe scripts. Agent-generated work should express them as Task Plan
steps so policy and confirmation remain in the path.

- Prefer `dump_nodes()` / `find_text()` / `tap_text()` over screenshots. The UI
  hierarchy is exact: every visible label comes back with a tap-ready center
  point `{text, desc, cls, pkg, res_id, x, y, w, h, clickable, ...}`.
- Tap by label: `tap_text("微信")`. On failure it raises with what IS visible,
  so read the exception before retrying.
- Tap by stable id: `tap_res_id("com.tencent.mm:id/title")` (ids survive label
  changes; prefer them in scripts you'll reuse).
- Unlabeled icons: `screenshot()`, view the image, compute the point (device
  px == tap coords), then `tap(x, y)`.
- **Verify after every action**: `wait_stable()` then `dump_nodes()` /
  `screenshot()`. The dump is the ground truth.
- Navigation: `home()`, `back()`, `open_app("微信")` (launcher icon),
  `launch("com.tencent.mm")` (package), `swipe(...)`, `type_text("hi")`,
  `type_unicode("中文")` (needs ADBKeyboard).
- **Scrolling a list**: `scroll_collect(extract, key=...)` walks a list to its
  true end, de-duping as it goes — returns `{items, stop, scrolls}` where `stop`
  is `'reached-end'` or `'max-scrolls'`. Use `scroll_until(done)` to stop when a
  predicate on the visible nodes is met. Both decide "done" from whether the
  **screen actually moved**, not from whether your parser found new rows. Each
  step settles first so lazy-loaded content arrives before the movement check.

## Consent

This is the user's real phone. Stop and ask before anything outward-facing or
hard to reverse: sending a message, posting, purchasing, deleting, changing
settings, installing apps. Navigating and reading for the user's own task is
fine, but don't linger in personal content (Messages, Photos, Mail) beyond what
the task needs.

## Task layer (one-line goals)

The historical builders remain, but `run_task` converts them to a strict plan
and routes them through policy:

```python
run_task([
    step_open("微信"),
    step_ask("确认打开文件传输助手?"),
    step_tap("文件传输助手"),
])
```

Step builders remain: `step_open`, `step_tap`, `step_tap_id`, `step_type`,
`step_type_unicode`, `step_wait`, `step_ask`. `step_ask` provides the prompt
for the next risky step; it is not authorization. Without a confirmer, the
risky step fails before ADB. The safe CLI is the recommended human flow.

Risk classification is capability-based. `home`, `back`, app opening, swiping,
and UI reads are safe. Any generic tap/resource tap/input requires confirmation.
`delete`, `install`, and `change_settings` are destructive. Policy never decides
from target strings, so translated or disguised labels do not bypass the gate.

## Connection is the user's job

The harness never connects the phone for you. Plugging in USB, enabling USB
debugging, and approving the authorization prompt are physical actions only the
user can do. `ensure_device()` gates every task on this: if the phone isn't
connected it raises a clear message. When you hit that:

- **STOP and relay the message. Ask the user to connect the phone themselves.**
- **Never** retry in a tight loop polling for the connection. The only fix is
  the user plugging in / approving. Retry once *after they confirm*, not before.

## Gotchas

- **`type_text` is ASCII-only.** Chinese/unicode needs ADBKeyboard installed
  and selected — then `type_unicode("中文")` works via broadcast. Without it,
  `type_text` raises on non-ASCII chars.
- **Unlocking the phone is the user's job.** If the screen is locked, taps land
  on the lock screen. Ask the user to unlock, then retry.
- **Coordinates are device pixels**, not logical dp. `wm size` gives the real
  resolution; the dump and `input` both use it, so no scaling is needed.
- **The window/content can move between calls.** `dump_nodes()` re-queries the
  tree every time, so never cache nodes across actions.
- No multi-touch (no pinch) via `input swipe`; some gestures need the app's own
  UI. Long-press works (`long_press(x, y)`).
