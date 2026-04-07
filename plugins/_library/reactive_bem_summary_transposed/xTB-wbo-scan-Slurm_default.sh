# ── SNIPPET: reactive_bem_summary_transposed/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Reactivity is defined only by first vs last frame delta (not max excursion).
#   - Diagonal keys are atom labels; off-diagonal keys are 'Ai-Aj' with i<j in label order.
#   - Output is transposed: one row per frame, one column per flagged key.
# Notes: Expects frame_*_bond_electrons.csv already present.
# ────────────────────────────────────────────────────────────

import csv
from pathlib import Path

def summarize_reactive_elements(workdir, thresh=0.5, out_csv="reactive_summary.csv", include_meta=False):
    """
    Compare first and last electron-BEM; pick entries with |Δ| >= thresh.
    For each flagged entry (diag or off-diag), write a row with its full time series.
    Row label convention:
      - diagonal: 'Rh1'
      - off-diagonal: 'C0-Rh1' with alphabetical order as produced in CSV (i<j)
    Columns: key, type, first, last, delta, frame_00000, frame_00001, ...
    """
    labels, mats, frames = _series_from_frames(workdir)
    if not mats:
        print("[reactive] No bond_electrons CSVs found; skipping.")
        return None
    n = len(labels)
    first = mats[0]
    last  = mats[-1]

    # numeric frame column names ("0","1",...)
    frame_cols = [str(k) for k in frames]

    # Build list of candidate keys
    candidates = []
    # diagonals → valence
    for i in range(n):
        dv = last[i][i] - first[i][i]
        if abs(dv) >= thresh:
            candidates.append(("valence", (i, i), labels[i]))
    # off-diagonals → bond (i<j)
    for i in range(n):
        for j in range(i+1, n):
            dv = last[i][j] - first[i][j]
            if abs(dv) >= thresh:
                candidates.append(("bond", (i, j), f"{labels[i]}-{labels[j]}"))

    # --- TRANSPOSED OUTPUT ---
    # Build a dict of {key -> full time series}
    key_to_series = {}
    for typ, (i, j), key in candidates:
        series = [m[i][j] for m in mats]
        key_to_series[key] = series

    # Sort keys (columns) for stable output
    keys_sorted = sorted(key_to_series.keys())

    # Header: frame index numbers only ("0","1","2",...)
    # Rows: one per frame; columns are the keys
    outp = Path(workdir) / out_csv
    with open(outp, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame"] + keys_sorted)
        for t, fr in enumerate(frames):
            row = [fr]
            for k in keys_sorted:
                row.append(key_to_series[k][t])
            writer.writerow(row)

    print(f"[reactive] Wrote {outp}")
    return str(outp)
