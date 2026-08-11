# Security Policy — android-harness

android-harness lets a local operator drive a real Android phone over ADB. The
production-safe interface does not execute model-generated source code:

```
LLM → JSON Task Plan → Policy Engine → Human Confirmation → Executor → ADB
```

## Trust boundaries

The phone owner is the trusted operator. LLM output, phone UI text, SMS, web
pages, notifications, plan files, and HTTP request bodies are untrusted. ADB,
the host account, and an unlocked phone are high-value capabilities.

The security boundary is formed by these modules:

- `plan.py` accepts a small, versioned JSON schema, rejects unknown fields and
  capabilities, limits sizes/ranges, and computes a canonical plan digest.
- `policy.py` owns validation, capability-based risk classification, and human
  authorization. It signs confirmation tokens over plan digest, step ID, risk,
  and a nonce.
- `executor.py` accepts only `TaskPlan` plus `Authorization`. Before every step
  it asks policy to verify authorization. It contains no safety heuristics.
- `llm.py` may generate JSON data only. Its output always goes through the same
  parser and policy as hand-written JSON.

## Risk model

Risk is never inferred from localized labels such as `发送`, `购买`, `删除`, or
`安装`. Labels are attacker-controlled UI data and are not a security boundary.

| Level | Capabilities | Behavior |
|---|---|---|
| `SAFE_NAVIGATION` | open app, home, back, swipe, bounded wait | no confirmation token needed |
| `SAFE_READ` | read UI hierarchy/screen metadata | no confirmation token needed |
| `USER_CONFIRM_REQUIRED` | every generic tap, resource tap, long press, text input, send, purchase | exact step must be confirmed |
| `DESTRUCTIVE` | delete, install, change settings | exact step must be confirmed with destructive warning |

Generic taps fail closed because a target label or coordinate cannot prove the
effect of the control. This is intentionally more conservative than keyword
filtering and remains safe if an LLM misclassifies a semantic action as a tap.

An `ask` step is only a human-facing prompt for the following risky step. It is
not a token and cannot authorize a preceding or subsequent action by itself.
The flow is `ask → human approval → plan-bound token → risky step`.

## Web and legacy Python

The web server refuses non-loopback bind addresses and rejects non-loopback
`Host`, cross-origin `Origin`, and non-JSON action requests to mitigate DNS
rebinding and browser CSRF. Unrestricted Python is disabled by default and its
endpoint returns a denial. `web.py --unsafe` enables the console only on
loopback and prints a prominent warning.

Risky Web plans use a server-side, five-minute, one-time confirmation challenge.
The first request stores the exact validated `TaskPlan` and its digest. The
browser confirms only the opaque challenge plus that digest; the server
atomically consumes the challenge and executes the stored plan without calling
the LLM again. Client-supplied replacement plans are ignored, digest mismatches
are rejected, and a bare `confirmed:true` is never authorization.

The default CLI never executes stdin as Python. Legacy trusted scripts require
the explicit `--unsafe-script` flag, which prints a warning and bypasses the
JSON policy boundary. Agent workspace Python is loaded only in that unsafe mode.

These unsafe modes protect against accidental exposure, not malicious local
users with access to the same OS account. Such users can invoke ADB directly.

## Attack surface

| Surface | Control |
|---|---|
| LLM output | strict JSON parser; no `exec`, imports, expressions, or callbacks |
| Risky ADB action | capability policy plus signed, plan-bound confirmation token |
| Prompt injection in UI text | text is data; generic taps/input fail closed |
| Web API | loopback/Host/Origin checks, one-time plan-bound challenges, size-limited JSON, Python off by default |
| Arbitrary host Python | explicit `--unsafe-script` / web `--unsafe` only |
| Device shell quoting | unicode input single-quote escaping; fixed argv where possible |
| Bundled APK | SHA-256 pinned below |

## Supply-chain note

`vendor/ADBKeyboard.apk` is bundled for Unicode input. Pinned SHA-256:

```
f9446fd3d7f775a764eb0df696b6819a7f3a4ea85bd17871855848ef72d6bb21  vendor/ADBKeyboard.apk
```

Do not replace this binary without updating the hash and recording provenance.

## Reporting a vulnerability

Do not open a public issue. Contact GitHub user `caowenfei29-spec` through a
draft Security Advisory or the repository Security tab. Include the code path,
minimal reproduction, impact, and a suggested fix if available. The target for
acknowledgement is seven days.
