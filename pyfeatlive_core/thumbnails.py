"""Face-crop thumbnails extracted from session videos for the Viewer
identity-cluster UI."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import av
import numpy as np
from PIL import Image


def extract_face_crop(
    video_path: Path,
    frame_idx: int,
    bbox: tuple[float, float, float, float],
    *,
    size: int = 96,
    pad_frac: float = 0.15,
) -> Optional[bytes]:
    """Decode the given frame of video_path, crop to a padded bbox
    around the face, resize to `size` square, return PNG bytes.

    Returns None if the frame can't be decoded (e.g. corrupt video,
    out-of-range index).
    """
    container = av.open(str(video_path))
    try:
        stream = container.streams.video[0]
        # Seek to approximate timestamp
        fps = float(stream.average_rate) if stream.average_rate else 30.0
        target_time = frame_idx / fps
        container.seek(int(target_time * stream.time_base.denominator),
                       stream=stream)
        rgb: Optional[np.ndarray] = None
        for frame in container.decode(video=0):
            if frame.pts is None:
                continue
            t = float(frame.pts * stream.time_base)
            if t >= target_time - (0.5 / fps):
                rgb = frame.to_ndarray(format="rgb24")
                break
        if rgb is None:
            return None
    finally:
        container.close()

    x, y, w, h = bbox
    H, W = rgb.shape[:2]
    pad = pad_frac * max(w, h)
    x0 = int(max(0, x - pad))
    y0 = int(max(0, y - pad))
    x1 = int(min(W, x + w + pad))
    y1 = int(min(H, y + h + pad))
    if x1 <= x0 or y1 <= y0:
        return None
    crop = rgb[y0:y1, x0:x1]
    img = Image.fromarray(crop, "RGB").resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
