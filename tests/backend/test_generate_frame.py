# tests/backend/test_generate_frame.py
import io
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import create_app

def _jpeg(arr):
    buf = io.BytesIO(); Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()

class _StubEditor:
    def edit_frame(self, rgb, *, expression, strength, mouth_mode):
        # echo a solid frame tinted by strength so the test can assert a real edit ran
        out = np.zeros_like(rgb); out[:] = int(min(255, strength * 255)); return out

@pytest.fixture
def client(monkeypatch):
    from backend.routers import generate as gen
    monkeypatch.setattr(gen, "_get_editor", lambda app: _StubEditor())
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_generate_frame_returns_edited_jpeg(client):
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    r = client.post("/api/generate/frame", content=_jpeg(arr),
                    headers={"Content-Type": "image/jpeg", "X-Strength": "0.5",
                             "X-Expression": "smile", "X-Mouth-Mode": "inpaint_v6"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    out = np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert out.shape == (120, 160, 3)
    assert abs(int(out.mean()) - 127) < 12   # strength 0.5 -> ~127 tint from the stub

def test_generate_frame_empty_body_400(client):
    r = client.post("/api/generate/frame", content=b"",
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 400
