# Auto-updater setup

Py-feat Live uses `tauri-plugin-updater` v2 for in-app updates. The
desktop app polls a `latest.json` manifest hosted on GitHub Releases;
when a newer version is available the splash window emits an
`updater://available` event the UI surfaces as an update banner.

This document covers the **one-time** setup needed before the first
release can be published.

## 1. Generate a signing keypair

The updater verifies that downloaded artifacts were signed with a
specific private key — separate from (and complementary to) macOS
code-signing. Without this, an attacker who compromised the GitHub
Release page could push a malicious update.

```sh
# From the repo root, with the Tauri CLI on PATH:
cd tauri
./node_modules/.bin/tauri signer generate -w ~/.tauri/pyfeatlive.key
```

You'll be prompted for a passphrase. Store it somewhere durable —
**this is unrecoverable** if lost; you'd have to ship a new public
key in a new release, breaking auto-update for existing installs.

The command produces:

- `~/.tauri/pyfeatlive.key`     — private key (KEEP SECRET)
- `~/.tauri/pyfeatlive.key.pub` — public key (commit to repo)

## 2. Embed the public key

Replace the placeholder in `tauri/src-tauri/tauri.conf.json`:

```json
"updater": {
  ...
  "pubkey": "PASTE_THE_CONTENTS_OF_pyfeatlive.key.pub_HERE"
}
```

The pubkey file is short (a single base64-ish line); paste exactly,
including any trailing characters.

## 3. Add GitHub Actions secrets

In the repo's *Settings → Secrets and variables → Actions*:

| Name | Value |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | `cat ~/.tauri/pyfeatlive.key | base64` (single line) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | passphrase you set above |
| `APPLE_CERTIFICATE` | `base64 < DeveloperIDApplication.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | password used when exporting the .p12 |
| `APPLE_SIGNING_IDENTITY` | `Developer ID Application: Cosanlab (TEAMID)` |
| `APPLE_ID` | Apple ID email used for notarytool |
| `APPLE_PASSWORD` | app-specific password from appleid.apple.com |
| `APPLE_TEAM_ID` | 10-char Team ID from your Apple Developer account |

Tauri's release action picks these up automatically.

## 4. Cut a release

```sh
git tag v1.0.0
git push origin v1.0.0
```

GHA does the rest:

1. Builds the .app per matrix entry (currently macOS arm64 + x86_64;
   Windows + Linux are scaffolded but commented out — uncomment in
   `.github/workflows/release.yml` when ready)
2. Code-signs with the Apple Developer ID
3. Submits to Apple notarytool, waits for approval, staples the ticket
4. Signs the artifacts with the Tauri private key
5. Uploads the signed .dmg + a `latest.json` manifest to the GitHub
   Release (created as a *draft* — review and publish manually)

## 5. How updates actually flow

Once a release is published:

```
                   GitHub Release: v1.1.0
                   ├── Py-feat.Live_1.1.0_aarch64.dmg
                   ├── Py-feat.Live_1.1.0_aarch64.dmg.sig
                   └── latest.json   {version: "1.1.0", platforms: {...}}
                                      │
                                      ▼ tauri-plugin-updater polls this URL
   ┌─────────────────────────────┐
   │ User running v1.0.0         │
   │  - boots Py-feat Live       │
   │  - check_for_update() runs  │
   │  - finds 1.1.0 > 1.0.0      │
   │  - emits updater://available│
   │  - splash shows "Update     │
   │    available" banner        │
   │  - user clicks → download   │
   │    + verify sig + apply     │
   │    + restart                │
   └─────────────────────────────┘
```

Note: the apply-update click handler is **not yet implemented in the
splash UI**. Currently the banner emits but doesn't act. Wiring the
"Apply" button is a small follow-up — `app.updater().download_and_install()`
plus a confirmation dialog.

## 6. What does *not* update via this channel

- The Python runtime venv (~1.5GB in `~/Library/Application Support/...`).
  That's installed once on first launch and reused across app versions.
  When the bundled `requirements.txt` changes, the Rust shell *should*
  detect the diff and run `uv pip sync` — currently the shell skips
  bootstrap if any venv exists, so this is a TODO. Workaround: bump
  the app version + delete the runtime dir to force a reinstall.
- HuggingFace model weights in `~/Library/Caches/...`. py-feat decides
  when to re-fetch.

For now: assume a Python runtime + model weights live for the lifetime
of the install. Major version bumps that change deps may need a
docs-led "delete the runtime dir, restart" step until the auto-sync
lands.
