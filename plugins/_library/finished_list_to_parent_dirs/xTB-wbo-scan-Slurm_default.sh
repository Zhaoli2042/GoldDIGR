# ── SNIPPET: finished_list_to_parent_dirs/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Only the first whitespace-separated token per line is treated as the TS path.
#   - Blank lines and comment lines starting with # are ignored.
#   - Parents are returned as absolute paths and deduplicated.
# Notes: Used by the zip summarizer.
# ────────────────────────────────────────────────────────────

import os
from typing import List

def load_parent_dirs(finished_path: str) -> List[str]:
    """Read finished.txt and return unique parent directories (absolute paths)."""
    parents = set()
    with open(finished_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Take the first whitespace-separated token as the TS directory path
            ts_dir = line.split()[0]
            parent = os.path.dirname(ts_dir)
            if parent:
                parents.add(os.path.abspath(parent))
    return sorted(parents)
