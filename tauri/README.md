# Py-feat Live — Tauri shell

Native desktop wrapper around `pyfeatlive`. Tauri (Rust) shell + system
WebView pointing at a bundled Python FastAPI (uvicorn) subprocess that
serves both the `/api/*` routes and the built Svelte SPA.

## Layout

```
tauri/
├── dist/                   built Svelte SPA (served by the sidecar)
├── src-tauri/
│   ├── src/
│   │   ├── main.rs         binary entry
│   │   └── lib.rs          spawn sidecar, kill on exit, open webview
│   ├── Cargo.toml
│   ├── tauri.conf.json     bundle config (externalBin → sidecar)
│   ├── capabilities/       v2 permission allow-list
│   ├── entitlements.plist  macOS hardened-runtime exemptions
│   ├── Info.plist          NSCameraUsageDescription
│   ├── icons/              app icons
│   └── binaries/           sidecar binary (dev shim or prod artifact)
└── package.json            (just to pull tauri-cli)

../sidecar/
├── sidecar.py              uvicorn entry (serves backend.main:app)
├── pyfeatlive.spec         PyInstaller spec
└── build.sh                produces a prod sidecar + drops it into
                            tauri/src-tauri/binaries/
```

## Development

Requirements: Rust 1.77+, Node 18+, an `.venv/` at the repo root with
pyfeatlive installed editably, and the Tauri CLI:

```bash
cd tauri
npm install
```

Then:

```bash
npm run tauri:dev
```

This:
1. Builds the Rust shell.
2. Tauri spawns `binaries/pyfeatlive-sidecar-<host-triple>`. In a fresh
   checkout that's the **dev shim**, a tiny shell script that runs the
   repo's `.venv/bin/python sidecar/sidecar.py`. It boots in ~10s
   instead of requiring a 20+ minute PyInstaller bundle first.
3. The native window opens to the loader (`setup.html`), which polls
   the sidecar's health endpoint on `http://127.0.0.1:8501/` and
   redirects to the app as soon as it's serving.

You should see a "Loading Py-feat Live…" splash, then the full
app inside a native window.

## Production build

```bash
# 1. Replace the dev shim with a real PyInstaller artifact
sidecar/build.sh

# 2. Bundle the .app / .dmg
cd tauri
npm run tauri:build
```

The PyInstaller step takes 10–30 minutes on a clean checkout (lots of
dependencies; torch alone is ~2GB to copy). Subsequent builds are
faster thanks to PyInstaller's intermediate cache.

## Code signing & notarization (macOS)

`tauri.conf.json` already wires the entitlements + Info.plist additions
the WebView camera capture and torch need (camera, JIT, dyld env vars,
library validation off — see `entitlements.plist` for the rationale).

To sign:

```bash
# In tauri/src-tauri/tauri.conf.json, set:
#   "macOS": { "signingIdentity": "Developer ID Application: <Your Name> (TEAMID)" }
# and export an APPLE_* env block for notarytool, then:
cd tauri
npm run tauri:build
```

Tauri will codesign the bundle and submit for notarization
automatically when those env vars are present. See
<https://v2.tauri.app/distribute/sign/macos/> for the full env block.

## Troubleshooting

- **"sidecar: $VENV/bin/python not found"**: the dev shim couldn't
  locate the repo's venv. Run `uv venv --python 3.12 .venv && uv pip
  install -e .` from the repo root.
- **Splash hangs forever**: the sidecar isn't reaching healthy. Check the
  Rust shell's stderr — sidecar stdout/stderr are forwarded there with
  `log::info!` / `log::warn!`. Run with `RUST_LOG=info npm run
  tauri:dev` to see them.
- **Webcam button does nothing**: macOS Camera permission. The OS
  prompts on first request; if you previously denied, re-enable in
  System Settings → Privacy & Security → Camera → Py-feat Live.
- **First launch is slow**: ~1GB of model weights download on first
  run (HuggingFace cache). The Rust shell sets `HF_HOME` to
  `~/Library/Caches/com.cosanlab.pyfeatlive/huggingface/` so subsequent
  launches reuse the cache.
