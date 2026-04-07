# ── SNIPPET: sdf_record_splitting_by_title/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Invariants:
#   - Record delimiter is a line whose stripped content equals '$$$$'.
#   - Title is the first line of the record; used as key (expected to match PREFIX labels).
#   - Each returned record includes the '$$$$\\n' terminator line.
# Notes: Enables fan-out of Auto3D multi-molecule SDF into per-prefix SDF files.
# ────────────────────────────────────────────────────────────

import os
from typing import List, Tuple

def _split_sdf_records_by_title(sdf_path: str) -> List[Tuple[str, List[str]]]:
    """
    Read an SDF file and split into (title, record_lines) for each molecule.
    Returns a list preserving order.
    """
    records: List[Tuple[str, List[str]]] = []
    if not os.path.exists(sdf_path):
        return records
    with open(sdf_path, "r") as f:
        lines = f.readlines()
    buf: List[str] = []
    for line in lines:
        if line.strip() == "$$$$":
            if buf:
                title = buf[0].rstrip("\n") if buf else ""
                records.append((title, buf + ["$$$$\n"]))
            buf = []
        else:
            buf.append(line)
    if buf:
        title = buf[0].rstrip("\n") if buf else ""
        records.append((title, buf + ["$$$$\n"]))
    return records
