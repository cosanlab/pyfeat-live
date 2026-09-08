# Releasing pyfeat-live

Releases are **tag-driven**: pushing a `vX.Y.Z` tag triggers
`.github/workflows/release.yml`, which builds the signed macOS `.dmg` and Windows
x86_64 NSIS/MSI installers, uploads them to a draft GitHub Release, and emits the
auto-updater `latest.json`. Windows Authenticode signing is enabled separately
after Azure identity validation; see [Windows code signing](docs/windows-code-signing.md).
`notify-pyfeat.yml` then runs on publish.

## Branch & review flow

`main` is protected — changes land via **pull request**, and **CI must pass**
(the `frontend` and `tauri` checks) before merge. No direct pushes to `main`.

1. Branch from `main`: `feat/...`, `fix/...`, etc.
2. Open a PR into `main`.
3. CI runs the frontend checks and a full unsigned Windows NSIS/MSI build.
4. Merge once CI is green.

## Cutting a release

1. **Bump the version** in all three files (keep them in sync):
   - `tauri/src-tauri/Cargo.toml` → `version`
   - `tauri/src-tauri/tauri.conf.json` → `version`
   - `tauri/src-tauri/Cargo.lock` → the `pyfeatlive-tauri` package entry
2. Write short, user-facing release notes.
3. PR → CI green → merge to `main`.
4. Tag and push from `main`:
   ```bash
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   `release.yml` uploads installers to a draft GitHub Release.
   You can also re-run a build for an existing tag via the workflow's
   `workflow_dispatch` input. Select that tag as the workflow ref as well when
   the `windows-signing` environment is restricted to release tags.
5. **Verify**: download the `.dmg` and Windows installer, install, and smoke-test — CI does not run
   the app. On first launch the runtime venv installs (torch / py-feat /
   pyfeat-generator from PyPI; model weights from the public `py-feat`
   HuggingFace org).

## Patch / hotfix

Same flow with the next patch version (e.g. `v0.8.14`). The auto-updater
notifies installed users, so always verify the `.dmg` before announcing.

## Versioning

`MAJOR.MINOR.PATCH`. Patch for fixes, minor for features, major for breaking
changes to the app or its data layout.
