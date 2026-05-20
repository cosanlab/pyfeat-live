"""pyfeatlive_core — framework-neutral facial-expression pipeline.

Houses the parts of pyfeat-live that don't depend on a particular UI
framework: detector loading, the streaming recorder, on-disk session
schema, identity tracking, annotations, and pipeline presets.

Imported by ``backend`` (FastAPI) for v2, and reusable from notebooks
or other Python entry points.
"""

__version__ = "2.0.0-dev"
