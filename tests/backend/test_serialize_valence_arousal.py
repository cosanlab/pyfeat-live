import pandas as pd
from backend.serialization import serialize_faces


def test_serialize_includes_valence_arousal():
    fex = pd.DataFrame([{
        "FaceRectX": 1.0, "FaceRectY": 2.0, "FaceRectWidth": 3.0, "FaceRectHeight": 4.0,
        "valence": -0.17, "arousal": 0.42,
    }])
    out = serialize_faces(fex, mp_landmarks=True)
    assert out[0]["valence_arousal"] == {"valence": -0.17, "arousal": 0.42}


def test_serialize_omits_valence_arousal_when_absent():
    fex = pd.DataFrame([{
        "FaceRectX": 1.0, "FaceRectY": 2.0, "FaceRectWidth": 3.0, "FaceRectHeight": 4.0,
    }])
    out = serialize_faces(fex, mp_landmarks=True)
    assert "valence_arousal" not in out[0]
