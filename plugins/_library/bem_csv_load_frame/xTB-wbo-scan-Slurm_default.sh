# ── SNIPPET: bem_csv_load_frame/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Header row must be labels with an empty top-left cell; data starts at row 2, col 2.
#   - Missing/blank/non-numeric entries must be treated as 0.0 (never crash).
# Notes: Used by time-series loader and reactive summarizer.
# ────────────────────────────────────────────────────────────

import csv

def _load_bem_e_csv(path):
    """
    Read frame_#####_bond_electrons.csv → (labels, matrix)
    labels: list like ['C0','H1',...]
    matrix: n×n float matrix (off-diags 0.0 if missing; diagonal may be blank→0.0)
    """
    with open(path, "r", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or not rows[0]:
        raise ValueError(f"Empty/invalid BEM CSV: {path}")
    labels = rows[0][1:]
    n = len(labels)
    mat = [[0.0]*n for _ in range(n)]
    for i in range(n):
        # row i+1: [row_label, v1, v2, ...]
        row = rows[i+1]
        for j in range(n):
            tok = row[j+1] if j+1 < len(row) else ""
            try:
                mat[i][j] = float(tok)
            except Exception:
                mat[i][j] = 0.0
    return labels, mat
