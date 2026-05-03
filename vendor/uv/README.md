# Vendored `uv` binaries

Tauri ships these inside the .app to drive the on-first-run install of
the Python runtime venv. One per host triple.

The current copy at `uv-aarch64-apple-darwin` is the host's
`/opt/homebrew/bin/uv` (Astral release, version pinned by Homebrew).
For real distribution this should be downloaded from Astral's release
tarballs to ensure architecture and version are locked:

```sh
# macOS arm64
curl -L https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz \
  | tar -xz -C vendor/uv/ --strip-components=1 uv-aarch64-apple-darwin/uv
mv vendor/uv/uv vendor/uv/uv-aarch64-apple-darwin

# macOS x86_64 (Intel)
curl -L https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-apple-darwin.tar.gz \
  | tar -xz -C vendor/uv/ --strip-components=1 uv-x86_64-apple-darwin/uv
mv vendor/uv/uv vendor/uv/uv-x86_64-apple-darwin
```

(repeat per platform pattern: `uv-x86_64-pc-windows-msvc`,
`uv-aarch64-unknown-linux-gnu`, `uv-x86_64-unknown-linux-gnu`).

The Tauri build config in `../../tauri/src-tauri/tauri.conf.json`
references these via `bundle.externalBin = ["../../../vendor/uv/uv"]`
(Tauri appends the host triple suffix at bundle time).

The Rust shell resolves the bundled path at runtime via
`app.shell().sidecar("uv")`.
