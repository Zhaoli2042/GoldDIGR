"""
pipeline.plugins.pilot – Deprecated. Use develop instead.

All pilot functionality has been merged into develop.py:
  - develop --real-data        (replaces pilot)
  - develop --prep-only        (replaces pilot --prep-only)
  - develop --resume <dir>     (replaces pilot --pilot-dir)

Shared utilities (scheduler detection, result collection) have
moved to _utils.py. This module re-exports them for backward
compatibility.
"""
from __future__ import annotations

# Re-export utilities that other modules may have imported from here.
# Canonical location is now _utils.py.
from ._utils import (
    detect_scheduler as _detect_scheduler,
    count_running_jobs as _count_running_jobs,
    get_held_jobs as _get_held_jobs,
    pick_representative_files as _pick_representative_files,
    collect_results as _collect_results,
)
