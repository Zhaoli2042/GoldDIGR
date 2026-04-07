# ── SNIPPET: reactive_summary_slope_events/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Data must be sorted by 'frame' before slope computation.
#   - Slope uses forward/backward difference at ends and central difference in interior.
#   - Top events are selected by descending |slope|.
# Notes: Expects reactive_summary.csv format produced by reactive_bem_summary_transposed.
# ────────────────────────────────────────────────────────────

from typing import Dict
import numpy as np
import pandas as pd

def compute_bond_slopes(df: pd.DataFrame, top_n: int = 3) -> Dict[str, dict]:
    """Compute first-derivative-like slopes for each bond column.

    We:
      * sort by the frame column
      * for each bond column, compute a slope at each frame:
          - frame 0: forward difference: v[1] - v[0]
          - last frame: backward difference: v[-1] - v[-2]
          - interior frames: central difference: (v[i+1] - v[i-1]) / 2
      * find the top |slope| values (up to top_n) and record their frames
    """
    if "frame" not in df.columns:
        raise ValueError("reactive_summary.csv is missing a 'frame' column")

    df_sorted = df.sort_values("frame").reset_index(drop=True)
    frames = df_sorted["frame"].to_numpy()
    result: Dict[str, dict] = {}

    for col in df_sorted.columns:
        if col == "frame":
            continue
        vals = df_sorted[col].to_numpy(dtype=float)
        n = len(vals)
        if n == 0:
            continue

        slopes = np.zeros(n, dtype=float)
        if n == 1:
            slopes[0] = 0.0
        elif n == 2:
            slopes[0] = vals[1] - vals[0]
            slopes[1] = slopes[0]
        else:
            slopes[0] = vals[1] - vals[0]
            slopes[-1] = vals[-1] - vals[-2]
            slopes[1:-1] = (vals[2:] - vals[:-2]) / 2.0

        order = np.argsort(-np.abs(slopes))  # descending by |slope|
        k = min(top_n, n)
        top_idx = order[:k]

        events = []
        for idx in top_idx:
            events.append(
                {
                    "frame": int(frames[idx]),
                    "slope": float(slopes[idx]),
                    "value": float(vals[idx]),
                }
            )

        result[col] = {
            "first": float(vals[0]),
            "last": float(vals[-1]),
            "delta": float(vals[-1] - vals[0]),
            "top_slope_events": events,
        }

    return result
