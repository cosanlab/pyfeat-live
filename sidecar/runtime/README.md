# Runtime dependency manifest

The user-data venv that gets installed on first launch is built from
`requirements.txt` in this directory. It's a fully hash-pinned lock
file — `--require-hashes` is enabled in the bootstrap so installs fail
loudly if anything is missing a hash.

## Workflow

1. Edit `requirements.in` (the human-readable input) — add/remove/bump
   pins as needed.
2. Regenerate the lock:

   ```sh
   # from the repo root. --python-platform is REQUIRED: this lock is installed
   # on the user's Mac (the .app's bundled runtime), so it must resolve for
   # macOS — NOT for whatever host runs the compile. Omitting it on a Linux/CUDA
   # box resolves torch's CUDA variant (nvidia-* / cuda-bindings), which has no
   # macOS wheels and makes the first-run `uv pip install` unsatisfiable.
   uv pip compile \
     --quiet \
     --generate-hashes \
     --python-version 3.12 \
     --python-platform aarch64-apple-darwin \
     --output-file sidecar/runtime/requirements.txt \
     sidecar/runtime/requirements.in
   ```

3. Commit both files together. The diff in `requirements.txt` makes
   review of dependency changes legible.

## Why `requirements.txt` and not a uv-style `pyproject.toml`?

- `pyproject.toml` + `uv.lock` are uv's preferred project layout, and
  they're great for development.
- `requirements.txt` (with hashes) is the universal lock format every
  Python installer understands — including older uv, pip, and pip-tools
  versions. It also gives a one-line install command (`uv pip install
  -r requirements.txt --require-hashes`) without needing the
  `pyproject.toml`'s tool config.

For a desktop app where the install runs on the *user's* machine with
*whatever* uv version we ship, the more universal format is the right
default.

## Why `--require-hashes`?

Defense-in-depth against a compromised PyPI mirror or typosquatted
package. The bundled Tauri public key already gates updates to the app
itself, but the Python deps come from PyPI — independent trust path.
The lock file plus `--require-hashes` means a swapped or tampered wheel
fails the install instead of silently shipping malware.

## Adding a new dep

1. Add the line to `requirements.in` (no version constraint needed —
   uv's resolver picks the latest compatible).
2. Re-run the compile command above.
3. Commit; review the lock diff to verify nothing unexpected got
   pulled in transitively.

## Bumping `py-feat`

`py-feat` is pinned by git ref in `requirements.in`:

```
py-feat @ git+https://github.com/cosanlab/py-feat@<commit-sha>
```

To bump: replace the SHA, re-run compile. The lock will record both
the git ref and a hash of the wheel uv builds locally from that ref.
