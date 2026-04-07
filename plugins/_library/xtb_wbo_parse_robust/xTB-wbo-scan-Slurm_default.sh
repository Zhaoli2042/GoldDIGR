# ── SNIPPET: xtb_wbo_parse_robust/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        xtb
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Pair-list indices are 1-based in file and must be converted to 0-based.
#   - If duplicate pair entries exist, keep the value with larger |value|.
#   - Matrix format is symmetrized by averaging mat[i][j] and mat[j][i].
# Notes: Returns empty dict if file missing or unrecognized.
# ────────────────────────────────────────────────────────────

import re
from pathlib import Path

WBO_PAIRLINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+([+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)\s*$")

def parse_wbo_file(wbo_path):
    """
    Parse xTB .wbo file.
    Supports:
      (A) Pair list format: 'i  j  value' (1-based indices)
      (B) Lower/upper triangular matrix (n lines of floats); we detect by row lengths.
    Returns: dict {(i,j): wbo} with 0-based indices and i<j.
    """
    wbo_pairs = {}
    if not Path(wbo_path).exists():
        return wbo_pairs

    with open(wbo_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip() and not ln.strip().startswith("#")]

    # Try (A) pair list
    hits = 0
    for ln in lines:
        m = WBO_PAIRLINE.match(ln)
        if m:
            i = int(m.group(1)) - 1
            j = int(m.group(2)) - 1
            v = float(m.group(3))
            if i != j:
                a, b = (i, j) if i < j else (j, i)
                prev = wbo_pairs.get((a, b))
                wbo_pairs[(a, b)] = v if (prev is None or abs(v) > abs(prev)) else prev
            hits += 1
    if hits > 0:
        return wbo_pairs

    # Try (B) triangular / square matrix
    # Detect row token counts
    token_rows = [ln.split() for ln in lines]
    lens = [len(r) for r in token_rows]
    n = max(lens) if lens else 0
    if n > 1 and all(all(re.match(r"[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?$", t) for t in row) for row in token_rows):
        # Accept either n rows or >= n rows; use first n rows of width <= n
        mat = [[0.0]*n for _ in range(n)]
        for i, row in enumerate(token_rows[:n]):
            for j, tok in enumerate(row[:n]):
                try:
                    mat[i][j] = float(tok)
                except:
                    mat[i][j] = 0.0
        # Symmetrize and extract upper triangle
        for i in range(n):
            for j in range(i+1, n):
                v = 0.5*(mat[i][j] + mat[j][i])
                if abs(v) > 0.0:
                    wbo_pairs[(i, j)] = v
        return wbo_pairs

    # Fallback: nothing recognized
    return wbo_pairs
