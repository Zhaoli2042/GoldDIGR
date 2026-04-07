# ── SNIPPET: jsonl_aggregate_over_parent_dirs/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Output directory is created if missing.
#   - Only files ending with .zip are scanned.
#   - Writes records streaming (no need to hold all in memory).
# Notes: This is the operational “STATUS/aggregation” artifact for downstream indexing.
# ────────────────────────────────────────────────────────────

import json, os, sys

def aggregate_jsonl(finished_path: str, out_path: str) -> None:
    parent_dirs = load_parent_dirs(finished_path)
    if not parent_dirs:
        print("[warn] No parent directories found from finished.txt", file=sys.stderr)

    out_path = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    n_zips_scanned = 0
    n_records = 0

    with open(out_path, "w") as out_f:
        for parent in parent_dirs:
            if not os.path.isdir(parent):
                print(f"[warn] Parent directory does not exist: {parent}", file=sys.stderr)
                continue

            for name in sorted(os.listdir(parent)):
                if not name.lower().endswith(".zip"):
                    continue
                zip_path = os.path.join(parent, name)
                n_zips_scanned += 1

                rec = process_zip(zip_path)
                if rec is None:
                    continue

                out_f.write(json.dumps(rec) + "\n")
                n_records += 1
                print(f"[info] Recorded summary for {zip_path}", file=sys.stderr)

    print(
        f"Done. Scanned {n_zips_scanned} zip files, wrote {n_records} records to {out_path}",
        file=sys.stderr,
    )
