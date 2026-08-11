# android-harness 🤖📱

Control a **real Android phone** from an LLM agent — no app changes, no root, no
emulator. It's a thin, editable harness modeled on `ShawnPana/phone-harness`,
but adapted to Android where the transport is cleaner.

The agent drives the phone through ADB:
- **Eyes** — `uiautomator dump` gives the real UI hierarchy (a DOM), not OCR.
  Every node carries its own text, content-desc, class, and tap-ready bounds.
  This is far more reliable than reading pixels.
- **Hands** — `adb shell input tap|swipe|text|keyevent` performs the actions.

```
  ● agent: wants to open WeChat
  │
  ● dump_nodes() → "微信" at (540, 2059), clickable
  │
  ● tap(540, 2059) → wait_stable() → current_app() confirms com.tencent.mm
  ✓ done
```

**Your phone, driven by an agent — and the eyes are exact.**

## Quick start

```bash
# 1) connect the phone (USB debugging on, authorized) — that part is your job
# 2) run the doctor
./android-harness --doctor

# 3) drive it
./android-harness <<'PY'
home()
open_app("微信")
tap_text("文件传输助手")
type_text("hello from the harness")
print([n["text"] for n in dump_nodes()][:10])
PY
```

## Why Android is the better target here

`ShawnPana/phone-harness` drives an iPhone through macOS iPhone Mirroring and
has to *OCR a screenshot* to know what's on screen — slow, and blind to
unlabeled icons. On Android, `uiautomator` hands the agent the actual view tree,
so `tap_text("设置")` is exact, not approximate. The hands are the same idea
(`input` instead of CGEvents).

## Layout

- `SKILL.md` — day-to-day usage (the agent-facing product surface)
- `install.md` — connection bootstrap and troubleshooting
- `src/android_harness/` — core (~500 lines):
  - `adb.py` — adb wrapper, input primitives, UI dump, connection state
  - `ui.py` — parse the uiautomator XML into tappable node dicts
  - `helpers.py` — the primitives pre-imported into scripts
  - `admin.py` — `--doctor`
  - `run.py` — the CLI (`exec` stdin with helpers in scope)
- `agent-workspace/agent_helpers.py` — helper code the agent edits; auto-loaded
  into every script's namespace

## Limits

- One phone, one session; the user must unlock / connect it (physical).
- No multi-touch (no pinch) via `input swipe`.
- `type_text` is ASCII-only; Chinese needs ADBKeyboard + `type_unicode`.
- The agent can't see through DRM video or past a locked screen.

## Safety

This is a real phone. The harness follows the consent model from
phone-harness-safe: stop and ask before anything outward-facing or hard to
reverse (send, post, buy, delete, change settings, install). Connecting the
phone is always the user's physical action — the harness never auto-connects.
