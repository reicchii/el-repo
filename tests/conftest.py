"""Pytest bootstrap for the Phantom Worlds Tier A backend.

Ensures two Windows-specific + import-path invariants before any test module
imports ``numpy`` (which is pulled in transitively by ``app.main``):

1. ``OPENBLAS_NUM_THREADS=1`` — numpy's OpenBLAS backend on Windows can raise
   ``MemoryError`` with the default thread count (see project tooling rules).
2. The backend root is on ``sys.path`` so ``app`` and ``tests`` resolve no
   matter how pytest is invoked (``pytest``, ``python -m pytest``, or an IDE).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))