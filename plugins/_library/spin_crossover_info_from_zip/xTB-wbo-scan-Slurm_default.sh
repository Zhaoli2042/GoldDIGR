# ── SNIPPET: spin_crossover_info_from_zip/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - spin_crossover_frames.txt is the presence marker; without it returns None.
#   - Frames are parsed as ints from whitespace/comma separated tokens and deduplicated/sorted.
#   - If spin_scan_summary.csv is missing or lacks required columns, still returns frames with empty events.
# Notes: Multiplicity is reported as best_UHF+1.
# ────────────────────────────────────────────────────────────

import io
from typing import List, Optional
import pandas as pd
import zipfile

def load_spin_crossover_info(
    z: zipfile.ZipFile, namelist: List[str]
) -> Optional[dict]:
    """Load spin crossover info (if present) from the zip."""
    sco_member = find_xtb_scan_member(namelist, "spin_crossover_frames.txt")
    if sco_member is None:
        return None

    # Read crossover frames
    with z.open(sco_member, "r") as f:
        text = f.read().decode("utf-8", errors="replace")
    frames: List[int] = []
    for tok in text.replace(",", " ").split():
        try:
            frames.append(int(tok))
        except ValueError:
            continue
    frames = sorted(set(frames))
    if not frames:
        return None

    # Load spin_scan_summary.csv to get best_UHF vs frame
    spin_member = find_xtb_scan_member(namelist, "spin_scan_summary.csv")
    if spin_member is None:
        # We know frames but not spins; still record frames
        return {"frames": frames, "events": []}

    with z.open(spin_member, "r") as f:
        df_spin = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8"))

    if "frame" not in df_spin.columns or "best_UHF" not in df_spin.columns:
        return {"frames": frames, "events": []}

    frame_to_best = {
        int(row["frame"]): int(row["best_UHF"])
        for _, row in df_spin.iterrows()
        if not pd.isna(row["frame"]) and not pd.isna(row["best_UHF"])
    }

    events = []
    for fr in frames:
        to_spin = frame_to_best.get(fr)
        from_spin = frame_to_best.get(fr - 1)
        event = {
            "frame": int(fr),
            "from_best_UHF": int(from_spin) if from_spin is not None else None,
            "to_best_UHF": int(to_spin) if to_spin is not None else None,
            "from_multiplicity": int(from_spin + 1) if from_spin is not None else None,
            "to_multiplicity": int(to_spin + 1) if to_spin is not None else None,
        }
        events.append(event)

    return {"frames": frames, "events": events}
