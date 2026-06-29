def test_faceeditor_importable():
    from pyfeat_generator import FaceEditor   # noqa: F401
    assert hasattr(FaceEditor, "edit_frame") and hasattr(FaceEditor, "edit_chip")
