## What this PR does

<!-- one paragraph -->

## Security checklist

- [ ] No new `exec` / `subprocess` / `adb.shell` call without input escaping
- [ ] Every new executor capability has an explicit policy classification
- [ ] No risky step executes without a plan-bound confirmation token
- [ ] No new bundled binary (or it's discussed + hash-pinned in SECURITY.md)
- [ ] I did **not** modify `agent-workspace/`  ← if you did, explain below

## Notes for the maintainer

<!-- anything you want reviewed closely -->
