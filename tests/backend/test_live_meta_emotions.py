"""Emotion serialisation via serialize_faces (replaces the old _live_meta_header test).

_live_meta_header was removed when the /api/live/frame handler switched from
returning a baked JPEG with JSON in an X-Live-Meta header to returning a JSON
body via serialize_faces.  This file retains the emotion-coverage assertion
against the new path.
"""

import pandas as pd
from backend.serialization import serialize_faces


def _fex_with_all_emotions():
    # One face row carrying a bbox + all 7 py-feat emotion columns.
    data = {
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 100.0, "FaceRectHeight": 120.0,
        "anger": 0.01, "disgust": 0.02, "fear": 0.03, "happiness": 0.19,
        "sadness": 0.23, "surprise": 0.04, "neutral": 0.38,
    }
    return pd.DataFrame([data])


def test_serialize_faces_emits_all_seven_emotions():
    """serialize_faces must include all 7 canonical emotions in face["emotions"]."""
    fex = _fex_with_all_emotions()
    faces = serialize_faces(fex, mp_landmarks=False)
    assert len(faces) == 1
    emo = faces[0]["emotions"]
    assert set(emo.keys()) == {
        "anger", "disgust", "fear", "happiness",
        "sadness", "surprise", "neutral",
    }
    assert len(emo) == 7
