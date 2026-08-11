# Publishing android-harness to PyPI

The package builds with **hatchling** and has **no runtime dependencies**
(stdlib only), so publishing is small and safe.

## One-time repo setup (maintainer only)

1. Create a PyPI account and a **API token** at https://pypi.org/manage/api-tokens/
2. In GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `PYPI_API_TOKEN`
   - Value: the token from step 1
3. (Optional) Add a `pypi` **environment** under Settings → Environments so the
   publish job is gated.

> The token lives only in GitHub Secrets. It is never committed to the repo.
> If leaked, revoke it immediately at pypi.org.

## To release a new version

1. Bump `version` in `pyproject.toml` (keep it in sync with the git tag).
2. Commit: `git commit -am "release: vX.Y.Z"`
3. Tag + push: `git tag vX.Y.Z && git push origin vX.Y.Z`
4. On GitHub, draft a **Release** from that tag and publish it.
   The `publish.yml` workflow fires automatically and uploads to PyPI.

After that, `pip install android-harness` works and the `android-harness`
command is available.
