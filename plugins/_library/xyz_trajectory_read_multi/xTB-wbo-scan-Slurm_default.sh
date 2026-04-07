# ── SNIPPET: xyz_trajectory_read_multi/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Frame header is a line containing only an integer natoms.
#   - Second line is treated as comment and preserved.
#   - Frames with malformed coordinate lines are skipped by advancing one line and retrying.
# Notes: Designed for finished_irc.trj-like files.
# ────────────────────────────────────────────────────────────

import re

XYZ_HEADER_INT = re.compile(r"^\s*(\d+)\s*$")

def read_multi_xyz_like_trj(path):
    recs = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    i, n = 0, len(lines)
    while i < n:
        m = XYZ_HEADER_INT.match(lines[i])
        if not m: i += 1; continue
        nat = int(m.group(1))
        if i+1+nat >= n: break
        comment = lines[i+1].rstrip("\n")
        block = lines[i+2:i+2+nat]
        symbols, coords, ok = [], [], True
        for ln in block:
            ps = ln.strip().split()
            if len(ps) < 4: ok=False; break
            sym = ps[0]
            try: x,y,z = map(float, ps[1:4])
            except: ok=False; break
            symbols.append(sym); coords.append((x,y,z))
        if ok:
            recs.append((symbols, coords, comment))
            i = i + 2 + nat
        else:
            i += 1
    return recs
