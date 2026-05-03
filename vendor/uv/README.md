# Vendored `uv` binaries

Tauri ships these inside the .app to drive the on-first-run install of
the Python runtime venv. One per host triple.

The binaries themselves are **not committed** to git (they're 40MB+
each — `vendor/uv/uv-*` is in `.gitignore`). Instead:

- **CI** — `.github/workflows/release.yml` downloads the per-target
  binary from Astral's GitHub release tarballs at build time, pinned
  by `UV_VERSION`. Keep that pin in sync with the version this
  README documents.
- **Local development** — fetch the host binary into this directory
  before running `cargo tauri dev`:

```sh
# macOS Apple Silicon
curl -L https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz \
  | tar -xz -C vendor/uv/ --strip-components=1 uv-aarch64-apple-darwin/uv
mv vendor/uv/uv vendor/uv/uv-aarch64-apple-darwin

# macOS Intel
curl -L https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-apple-darwin.tar.gz \
  | tar -xz -C vendor/uv/ --strip-components=1 uv-x86_64-apple-darwin/uv
mv vendor/uv/uv vendor/uv/uv-x86_64-apple-darwin
```

(repeat per platform pattern: `uv-x86_64-pc-windows-msvc`,
`uv-aarch64-unknown-linux-gnu`, `uv-x86_64-unknown-linux-gnu`).

The Tauri build config in `../../tauri/src-tauri/tauri.conf.json`
references these via `bundle.externalBin = ["../../vendor/uv/uv"]`
(Tauri appends the host triple suffix at bundle time).

The Rust shell resolves the bundled path at runtime via
`app.shell().sidecar("uv")`.
