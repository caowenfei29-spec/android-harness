# Security Policy — android-harness

android-harness lets an LLM agent drive a **real Android phone** over ADB.
That is a powerful primitive: the agent can read the screen, tap, type,
launch apps, and run arbitrary `adb shell` commands. This document describes
what the harness does, where the real attack surface is, and how we keep it
from becoming a tool that harms the phone's owner.

## Threat model

The phone owner is the trusted operator. The things the **agent reads from the
phone screen** are *not* trusted: SMS, web pages, app content, notifications —
any of these may contain text crafted to mislead the agent (prompt injection).
The agent must never act on that text in a way that is outward-facing or hard
to reverse (send, post, buy, delete, change settings, install) without an
explicit, human-visible stop-and-ask gate.

## Attack surface (real, in code today)

| Surface | Where | Risk | Status |
|---|---|---|---|
| Arbitrary Python exec | `run.py` (CLI stdin), `web.py` `_run_script` | Agent/operator code runs on host | by design; web console needs auth+allowlist (TODO) |
| Arbitrary device commands | `adb.shell()` | Any `adb shell` string executes on phone | bounded by stop-and-ask for outward actions |
| Shell string interpolation | `type_unicode` (`am broadcast`) | Unescaped `msg` could break out of quotes | **Fixed** (quote escaping added) |
| Untrusted on-screen text | `dump_nodes` / `find_text` | Prompt injection → unwanted actions | Mitigated by stop-and-ask consent model |
| Bundled binary | `vendor/ADBKeyboard.apk` | Supply-chain provenance | Hash pinned below |
| Auto-exec of repo code | `agent-workspace/agent_helpers.py` loaded + `exec`'d | Malicious PR to that file runs on load | Reviewed manually; PRs must flag changes |

## Supply-chain note

`vendor/ADBKeyboard.apk` is bundled so Chinese/unicode input works without a
network download. Source: ADBKeyboard (open-source IME, widely mirrored on
F-Droid/GitHub). Pinned SHA-256:

```
f9446fd3d7f775a764eb0df696b6819a7f3a4ea85bd17871855848ef72d6bb21  vendor/ADBKeyboard.apk
```

Do not replace this binary without updating the hash above and recording why.

## Consent model

The harness follows a "stop and ask" rule: before anything outward-facing or
hard to reverse, the agent must pause and get the human's confirmation.
Connecting the phone (USB + USB debugging approval) is always a **physical**
action by the owner — the harness never auto-connects. Pull requests that
weaken this model are rejected.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

- Email the maintainer (GitHub user `caowenfei29-spec`) via a GitHub Security
  Advisory draft, or file a private report through the repo's "Security" tab.
- Include: what you found, the exact code path, a minimal reproduction, and
  suggested fix if any.
- Response target: within 7 days for acknowledgement.

## Scope of maintenance

This is a single-maintainer project. Security fixes take priority over
features. Every release must re-check the attack-surface table above.
