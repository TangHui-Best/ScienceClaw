"""Ensure the focused new-domain tests import from this worktree's backend."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND = Path(__file__).parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
