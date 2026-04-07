# ── SNIPPET: directory_structure_mirroring/copy2_with_auto_mkdir_parents ─
# Scheduler:   any
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: Used for provenance artifacts (logs, encoded SDFs).
# ────────────────────────────────────────────────────────────

import os
import shutil

def write_file(src: str, dst: str) -> None:
    ensure_dir(os.path.dirname(dst))
    shutil.copy2(src, dst)
