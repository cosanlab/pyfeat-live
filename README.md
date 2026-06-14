# Py-feat live

Real-time facial expression analysis. Webcam → py-feat detection → live overlays. Plus a Viewer for recorded sessions and an Analyze page for batch processing files.

## Install + run (desktop app)

The polished path is the Tauri-bundled desktop app:

1. Download the latest `.dmg` / `.exe` from [releases](https://github.com/cosanlab/pyfeat-live/releases).
2. Install and launch. First run downloads model weights (a few minutes; cached after).

## Run from source (dev)

```bash
git clone https://github.com/cosanlab/pyfeat-live.git
cd pyfeat-live
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Two terminals:

```bash
# Terminal 1 — backend (FastAPI on :8765)
.venv/bin/python -m uvicorn backend.main:app --reload --port 8765

# Terminal 2 — frontend (Svelte 5 + Vite on :5173)
cd frontend && pnpm install && pnpm dev
```

Open <http://localhost:5173>. Grant camera permission when prompted.

For a single-process dev launch (no HMR, but no Vite either):

```bash
cd frontend && pnpm build && cd ..
pyfeat-live   # boots FastAPI + opens browser at http://127.0.0.1:8765
```

### Tests

```bash
.venv/bin/python -m pytest tests/backend tests/core   # ~92 passing
cd frontend && pnpm check && pnpm build                # type-check + build
```

## Pages

### Live

Real-time webcam → py-feat detection → overlay-on-face rendering.

- **Detector / Models / Compute / Camera** in the sidebar (collapsible).
- **Detection size** preset picker — trades resolution for speed.
- **Landmark style** — points / lines / mesh.
- **Overlay chips** — Faceboxes / Landmarks / Pose / Gaze (MP only) / AUs / Emotions.
- **Stream controls** — Start / Pause / Stop the camera; recording is a separate Record button.
- Records to `~/Documents/pyfeat-live/sessions/<timestamp>/` as `video.mp4 + fex.csv + metadata.json`.

Live uses an **image-stream bake-and-return** pipeline. The frontend
posts each camera frame to the backend as JPEG. The backend bakes
detection overlays onto the frame using the most recently cached
detection result, then returns the baked frame as JPEG bytes. The
frontend paints the response to a canvas. Detection runs decoupled
in a background executor (~10 Hz) so the display tracks the round-
trip rate (15-25fps depending on machine), not the detection rate.

Overlays are pixels in the returned image — never re-encoded
through a video codec — so they stay sharp. Recording mode is
independent: `clean` records the source frames (Viewer can re-apply
overlays from `fex.csv` later), `overlay` records the baked frames
(overlays burned in for a share-out clip).

### Viewer

Loads a recorded session, plays the video, draws overlays from the saved Fex CSV, lets you scrub, annotate, and assign identities to faces.

- Left sidebar: Sessions tab (list of recordings) + Annotations tab (event / exclude / custom markers).
- Center: video stage + scrub bar with annotation lane + unified time-series plot.
- Right: per-frame Frame / Identities / numeric AU + emotion bars.
- Click any face in the video → IdentityAssignDialog (create new or assign existing).
- Press `E` for event marker, `C` for custom, shift+drag on scrub for exclude range.
- Plot supports multi-select on identities AND series (chips). Click plot x-axis to seek.

### Analyze

Batch-process video / image files. Drop into the queue; each file gets a per-file pipeline snapshot from the active preset (or override via the gear icon).

- Built-in presets: `MP · standard`, `MP · fast (cpu)`, `Classic · img2pose`, `Classic · retinaface`. Save custom presets via the preset modal.
- Run queue with chosen compute device + batch size.
- WebSocket pushes per-item progress.
- Completed items become sessions you can open in the Viewer.

## Architecture

| Layer | Lives in |
|---|---|
| Desktop shell (Rust, webview, code-signing, installer) | `tauri/` |
| Static SPA assets bundled into the Tauri binary | `tauri/dist/` (output of `frontend/`) |
| Frontend (Svelte 5 + Vite + Tailwind + @lucide/svelte) | `frontend/` |
| HTTP + WebSocket API | `backend/` (FastAPI) |
| Framework-neutral pipeline (detector, recorder, sessions, identities, annotations, presets) | `pyfeatlive_core/` |
| `pyfeat-live` CLI entry | `pyfeatlive/entry_point.py` |
| Tauri-sidecar Python launcher | `sidecar/sidecar.py` |

The Tauri shell spawns `sidecar.py` (which spawns uvicorn) as a child process, then opens the webview at `http://127.0.0.1:8765/`. The backend serves both `/api/*` and the bundled SPA, so the webview never crosses an origin.

## Profiling

`PYFEAT_LIVE_PROFILE=1 .venv/bin/python -m uvicorn backend.main:app --port 8765` logs per-frame timing breakdown of the detection pipeline (`recv / decode / lock_wait / detect / serialize`). Toggle the matching frontend instrumentation in the browser console with `window.__pyfeatProfile = true`.

If you run into installation issues with py-feat see [this issue](https://github.com/cosanlab/py-feat/issues/186).

## License

The Py-feat Live application code is released under the [MIT License](LICENSE).

**The facial-expression detection models are not covered by MIT.** The app
downloads and runs pretrained models (via py-feat) that are licensed
separately by their authors, and **several carry non-commercial / research-only
stipulations**. You are responsible for reviewing and complying with each
model's license before use — see the [py-feat model reference](https://py-feat.org/).
