# android-harness 🤖📱

Control a **real Android phone** from an LLM agent — no app changes, no root, no
emulator. It's a thin, editable harness modeled on `ShawnPana/phone-harness`,
but adapted to Android where the transport is cleaner.

Repo: https://github.com/caowenfei29-spec/android-harness

[![CI](https://github.com/caowenfei29-spec/android-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/caowenfei29-spec/android-harness/actions/workflows/ci.yml)
License: [MIT](LICENSE) · Security: [SECURITY.md](SECURITY.md) · Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)

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

# 3) produce auditable JSON, then execute it
./android-harness plan "Open 微信" > plan.json
./android-harness execute plan.json
```

The default CLI never executes generated Python. For a risky plan, review the
JSON and use `android-harness execute plan.json --confirm`; each risky step is
shown and bound to a one-plan confirmation token before ADB is called.

## Install

From source (recommended for editing the skill):

```bash
git clone https://github.com/caowenfei29-spec/android-harness
cd android-harness
pip install -e . --no-deps
android-harness --doctor
```

From PyPI (once published):

```bash
pip install android-harness
```

Runtime is **standard-library only** (Python ≥ 3.10); the build backend is
hatchling. See [PUBLISH.md](PUBLISH.md) for the release flow.

## Safety & trust

This harness drives a **real phone**. Its default execution chain is:

```
LLM → JSON Task Plan → Policy Engine → Human Confirmation → Executor → ADB
```

The executor accepts only validated JSON capabilities and never Python source.
Risk comes from the capability type, not labels such as `发送` or `Delete`.
Generic taps and input fail closed and require confirmation; destructive and
settings capabilities receive the stricter `DESTRUCTIVE` classification. Read
[SECURITY.md](SECURITY.md) for the threat model and the current attack-surface
table before wiring it into an agent.

Unrestricted Python remains available only as an explicit compatibility escape
hatch for trusted local scripts:

```bash
android-harness --unsafe-script trusted-script.py
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
- `src/android_harness/` — core package:
  - `adb.py` — adb wrapper, input primitives, UI dump, connection state
  - `ui.py` — parse the uiautomator XML into tappable node dicts
  - `helpers.py` — low-level trusted primitives used by the executor and unsafe scripts
  - `plan.py` — strict JSON schema, parser, canonical digest
  - `policy.py` — validation, risk classification, confirmation authorization
  - `executor.py` — JSON-only ADB execution; no safety decisions
  - `task.py` — compatibility builders backed by policy + executor
  - `admin.py` — `--doctor`
  - `run.py` — `plan`, `execute`, and explicit `--unsafe-script` modes
- `agent-workspace/agent_helpers.py` — optional trusted code loaded only by
  explicit unsafe script mode

## Limits

- One phone, one session; the user must unlock / connect it (physical).
- No multi-touch (no pinch) via `input swipe`.
- `type_text` is ASCII-only; Chinese needs ADBKeyboard + `type_unicode`.
- The agent can't see through DRM video or past a locked screen.

## Safety

This is a real phone. No confirmation token means no risky execution. An `ask`
step supplies a human prompt but is not itself authorization; policy must
receive approval and mint a token bound to the exact plan and step. Connecting
the phone is always the user's physical action.
