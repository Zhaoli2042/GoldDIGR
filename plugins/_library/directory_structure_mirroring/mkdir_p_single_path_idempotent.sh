# ── SNIPPET: directory_structure_mirroring/mkdir_p_single_path_idempotent ─
# Scheduler:   any
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: Used across all scripts to guarantee output directories exist.
# ────────────────────────────────────────────────────────────

import os

def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
