"""``pyfeat-live`` package — v2 stack.

Most logic lives in:
  - backend/         (FastAPI app)
  - pyfeatlive_core/ (framework-neutral pipeline)
  - frontend/       (Svelte SPA)

This package only carries the CLI entry point (entry_point.py) and the
package version metadata.
"""

__version__ = "2.0.0-dev"
