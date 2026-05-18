"""Root conftest: ensure the project root is on sys.path so that
``backend`` and ``pyfeatlive_core`` are importable regardless of whether
pytest's rootdir auto-insertion fires (it doesn't always fire when test
sub-packages have __init__.py files).
"""

import sys
from pathlib import Path

# Insert the repo root at position 0 so project-local packages shadow any
# installed copies.
ROOT = str(Path(__file__).parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
