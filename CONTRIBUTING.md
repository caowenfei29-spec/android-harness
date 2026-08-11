# Contributing to android-harness

Thanks for interest in the project. It is small and single-maintainer, but
contributions are welcome — especially security reviews and clear bug fixes.

## Before you open a PR

1. Keep it focused. One logical change per PR.
2. If you change anything under `agent-workspace/`, **say so explicitly** in
   the PR description. It is loaded only by explicit `--unsafe-script` mode,
   but still runs as trusted host Python and is reviewed line by line.
3. No new bundled binaries unless discussed first (supply-chain risk).

## Security-sensitive changes

- Any new `exec`, `subprocess`, `adb.shell`, or shell-string interpolation
  must quote/escape untrusted input. See the `type_unicode` fix for the
  pattern: `'` → `'\''`.
- Do not bypass `TaskPlan → PolicyEngine → Authorization → Executor`.
- Risk must be classified by capability, never localized UI label text.
- If your PR touches a security control, ping the maintainer to confirm scope.

## Running locally

```bash
git clone <this-repo>
cd android-harness
pip install -e . --no-deps
python -m android_harness.run --help   # CLI loads
python -m android_harness.run --doctor # needs a real phone over USB
```

You don't need a phone to review most logic; the uiautomator parser and
helpers import without a device.

## Code style

- Standard library only at runtime (build backend is hatchling).
- Keep docstrings honest about what runs on the phone vs. the host.
- Add a test under `tests/` when you fix a parser/helper bug.
