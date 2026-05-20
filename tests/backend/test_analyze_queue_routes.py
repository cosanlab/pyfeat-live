"""Analyze queue CRUD + run lifecycle."""

import io
from pathlib import Path

import pytest


@pytest.fixture
def analyze_upload(tmp_path, monkeypatch):
    # Direct generated session files to tmp_path so we don't touch
    # ~/Documents during tests.
    monkeypatch.setattr(
        "backend.routers.analyze.default_sessions_root",
        lambda: tmp_path,
    )
    return tmp_path


def test_queue_starts_empty(client, analyze_upload):
    r = client.get("/api/analyze/queue")
    assert r.status_code == 200
    assert r.json() == []


def test_add_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    r = client.post("/api/analyze/queue", files=files, data=data)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["filename"] == "img.jpg"
    assert item["status"] == "queued"
    listing = client.get("/api/analyze/queue").json()
    assert len(listing) == 1


def test_delete_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    item_id = client.post("/api/analyze/queue", files=files, data=data).json()["id"]
    r = client.delete(f"/api/analyze/queue/{item_id}")
    assert r.status_code == 204
    assert client.get("/api/analyze/queue").json() == []


def test_patch_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    item_id = client.post("/api/analyze/queue", files=files, data=data).json()["id"]
    r = client.patch(f"/api/analyze/queue/{item_id}", json={
        "pipeline": {"detector_type": "Detector", "face_model": "img2pose",
                     "landmark_model": "mobilefacenet", "au_model": "xgb",
                     "emotion_model": "resmasknet", "identity_model": "arcface",
                     "preset_id": None, "preset_name": None},
    })
    assert r.status_code == 200
    assert r.json()["pipeline"]["detector_type"] == "Detector"


def test_run_processes_one_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    item_id = client.post("/api/analyze/queue", files=files, data=data).json()["id"]
    r = client.post("/api/analyze/run", json={
        "compute": "cpu", "batch_size": 1,
    })
    assert r.status_code == 202
    # Poll the queue until the item moves out of 'queued'/'running'.
    import time
    deadline = time.time() + 120
    while time.time() < deadline:
        items = client.get("/api/analyze/queue").json()
        statuses = {i["status"] for i in items}
        if statuses & {"done", "failed"}:
            break
        time.sleep(0.5)
    items = client.get("/api/analyze/queue").json()
    assert items[0]["status"] == "done", items[0]
    assert items[0]["session_dir"] is not None
