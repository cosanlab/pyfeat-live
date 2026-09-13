#!/usr/bin/env python3
"""End-to-end probe for an installed Py-feat Live: run AFTER launching the app.

Exercises the same path a real first launch takes, in order:

  1. wait for the sidecar's /api/system/health on one of the shell's ports
     (first launch: uv venv + ~1.5 GB dependency install happens here);
  2. GET /api/system/compute — proves `import torch` succeeded in the
     installed venv (native DLL / dylib load, the part a dry-run install
     can't verify);
  3. POST /api/live/configure with device=cpu — builds a real Detectorv2
     (downloads the model weights from Hugging Face);
  4. POST a fixture JPEG to /api/live/frame until a face comes back —
     one full detection pass through the pipeline.

Stdlib only so it runs on a bare runner python. Exit 0 on success, 1 on
any failure, with the last observed state printed for the job log.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Must match SIDECAR_PORT_RANGE in tauri/src-tauri/src/lib.rs.
PORTS = range(18640, 18650)


def _get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url: str, body: bytes, content_type: str, timeout: float):
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _log(msg: str) -> None:
    print(f"[smoke {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def wait_for_health(timeout_s: float) -> str:
    """Return the base URL of OUR sidecar, or raise after timeout_s."""
    deadline = time.monotonic() + timeout_s
    last_err = "no port answered yet"
    next_progress = 0.0
    while time.monotonic() < deadline:
        for port in PORTS:
            base = f"http://127.0.0.1:{port}"
            try:
                h = _get(f"{base}/api/system/health", timeout=3)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last_err = f"{port}: {exc}"
                continue
            # The `app` marker is what the Rust shell checks too — it rules
            # out an unrelated localhost service on the same port.
            if h.get("app") == "pyfeatlive" and h.get("status") == "ok":
                _log(f"sidecar healthy on {base}: {h}")
                return base
            last_err = f"{port}: unexpected health body {h!r}"
        if time.monotonic() >= next_progress:
            remaining = int(deadline - time.monotonic())
            _log(f"waiting for sidecar health ({remaining}s left; last: {last_err})")
            next_progress = time.monotonic() + 30
        time.sleep(5)
    raise RuntimeError(f"sidecar never became healthy: {last_err}")


def check_compute(base: str) -> None:
    c = _get(f"{base}/api/system/compute", timeout=30)
    _log(f"compute backends: {c}")
    if not c.get("cpu", {}).get("available"):
        raise RuntimeError(f"cpu backend not reported available: {c!r}")


def configure_detector(base: str, timeout_s: float) -> None:
    _log("building Detectorv2 on cpu (downloads model weights on first run)…")
    t0 = time.monotonic()
    body = json.dumps({"detector_type": "Detectorv2", "device": "cpu"}).encode()
    resp = _post(f"{base}/api/live/configure", body, "application/json", timeout=timeout_s)
    _log(f"detector configured in {time.monotonic() - t0:.0f}s: {resp}")


def detect_face(base: str, image: Path, timeout_s: float) -> dict:
    """POST the fixture until the (async) detection reports a face."""
    jpeg = image.read_bytes()
    deadline = time.monotonic() + timeout_s
    last = None
    frame_id = 0
    while time.monotonic() < deadline:
        frame_id += 1
        req = urllib.request.Request(f"{base}/api/live/frame", data=jpeg, method="POST")
        req.add_header("Content-Type", "image/jpeg")
        req.add_header("X-Frame-Id", str(frame_id))
        with urllib.request.urlopen(req, timeout=120) as r:
            last = json.loads(r.read())
        faces = last.get("faces") or []
        if faces:
            face = faces[0]
            keys = sorted(face.keys()) if isinstance(face, dict) else type(face).__name__
            _log(f"detected {len(faces)} face(s) after {frame_id} uploads; face keys: {keys}")
            return last
        time.sleep(1)
    raise RuntimeError(f"no face detected within {timeout_s:.0f}s; last response: {last!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", type=Path, required=True, help="JPEG with one clear face")
    ap.add_argument("--health-timeout", type=float, default=25 * 60,
                    help="seconds to wait for first-run install + sidecar start")
    ap.add_argument("--configure-timeout", type=float, default=15 * 60,
                    help="seconds allowed for model download + detector build")
    ap.add_argument("--detect-timeout", type=float, default=5 * 60)
    ap.add_argument("--skip-detection", action="store_true",
                    help="stop after the health + torch checks")
    args = ap.parse_args()

    if not args.image.is_file():
        _log(f"fixture image not found: {args.image}")
        return 1

    try:
        base = wait_for_health(args.health_timeout)
        check_compute(base)
        if args.skip_detection:
            _log("PASS (health + torch import)")
            return 0
        configure_detector(base, args.configure_timeout)
        detect_face(base, args.image, args.detect_timeout)
    except Exception as exc:  # noqa: BLE001 — any failure is a red build
        _log(f"FAIL: {exc}")
        return 1
    _log("PASS (health + torch import + detector build + one detection)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
