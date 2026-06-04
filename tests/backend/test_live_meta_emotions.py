import json
import numpy as np
import pandas as pd
from backend.routers.live import _live_meta_header


def _row_with_all_emotions():
    # One face row carrying a bbox + all 7 py-feat emotion columns.
    data = {
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 100.0, "FaceRectHeight": 120.0,
        "anger": 0.01, "disgust": 0.02, "fear": 0.03, "happiness": 0.19,
        "sadness": 0.23, "surprise": 0.04, "neutral": 0.38,
    }
    return pd.DataFrame([data])


def test_meta_header_emits_all_seven_emotions():
    fex = _row_with_all_emotions()
    header = _live_meta_header(fex, frame_dims=(640, 360))
    meta = json.loads(header)
    emo = meta["faces"][0]["emo"]
    names = {name for name, _ in emo}
    assert names == {
        "anger", "disgust", "fear", "happiness",
        "sadness", "surprise", "neutral",
    }
    assert len(emo) == 7
