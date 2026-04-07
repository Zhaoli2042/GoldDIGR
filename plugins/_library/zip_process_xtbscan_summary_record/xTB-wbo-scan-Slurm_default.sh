# ── SNIPPET: zip_process_xtbscan_summary_record/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Skip archives that do not contain any 'xTB-scan/' member.
#   - Do not emit a record unless reactive_summary.csv exists under xTB-scan/.
#   - Read only needed members (selective extraction) to keep it scalable.
# Notes: Intended for JSONL aggregation.
# ────────────────────────────────────────────────────────────

import io, os, sys, zipfile
import pandas as pd

def process_zip(zip_path: str) -> dict | None:
    """Process a single .zip archive."""
    try:
        z = zipfile.ZipFile(zip_path, "r")
    except Exception as e:
        print(f"[warn] Failed to open zip {zip_path}: {e}", file=sys.stderr)
        return None

    with z:
        namelist = z.namelist()

        # Skip zips that do not contain xTB-scan/ at all
        if not any("xTB-scan/" in name for name in namelist):
            return None

        # TS info from finished_irc.trj
        trj_member = find_member(namelist, "finished_irc.trj")
        ts_frame = None
        ts_energy = None
        n_frames = None
        if trj_member is not None:
            with z.open(trj_member, "r") as f:
                ts_frame, ts_energy, n_frames = parse_ts_from_trj(f.read())

        # Reactive summary (required to emit a record)
        reactive_member = find_xtb_scan_member(namelist, "reactive_summary.csv")
        if reactive_member is None:
            return None

        with z.open(reactive_member, "r") as f:
            df_reactive = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8"))

        bond_summary = compute_bond_slopes(df_reactive, top_n=3)

        rec: dict = {
            "zip_path": os.path.abspath(zip_path),
            "ts_frame": int(ts_frame) if ts_frame is not None else None,
            "ts_energy": float(ts_energy) if ts_energy is not None else None,
            "n_frames": int(n_frames) if n_frames is not None else None,
            "reactive_bonds": bond_summary,
        }

        # Spin crossover (optional)
        sco_info = load_spin_crossover_info(z, namelist)
        if sco_info is not None:
            rec["spin_crossover"] = sco_info

        return rec
