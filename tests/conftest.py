"""Puts the repo root on sys.path so `backend` and `core` import when pytest is started from anywhere."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
