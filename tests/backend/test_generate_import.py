def test_faceeditor_importable():
    from au_face_generation import FaceEditor   # noqa: F401
    assert hasattr(FaceEditor, "edit_frame") and hasattr(FaceEditor, "edit_chip")
