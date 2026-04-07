# ── SNIPPET: finished_list_to_parent_dirs/unique_nonempty_line_reader ─
# Scheduler:   any
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: Used to deduplicate SMILES/PREFIX input lines before batching.
# ────────────────────────────────────────────────────────────

import os
from typing import List

def read_unique_lines(file_path: str) -> List[str]:
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r") as f:
        return list({line.strip() for line in f if line.strip()})
