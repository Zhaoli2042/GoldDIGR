# ── SNIPPET: benchmark_json_schema_aggregator_to_finished_failed_missing/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      get_auto3d_calc_status
# Invariants:
#   - Assumes benchmark JSON fields: batch_id, hostname, slurm.partition, slurm.job_id, elapsed_hms, counts{done,total,failed}, batch_json_path, completed_smiles, per_smiles_status.
#   - Missing set computed as: original - finished - failed.
#   - Failed SMILES are those with per_smiles_status[smiles] == 'fail'.
# Notes: This is the ROUND2/resume driver for iterative retries (produces next input lists).
# ────────────────────────────────────────────────────────────

import os
from typing import List, Dict, Any

def aggregate_benchmarks_and_write_lists() -> None:
    smiles_prefix_map = {}
    if ORIGINAL_SMILES_PATH:
        print(f"Loading original SMILES list from: {ORIGINAL_SMILES_PATH}")
        smiles_prefix_map = load_smiles_prefix_map(ORIGINAL_SMILES_PATH)
    else:
        print("WARNING: ORIGINAL_SMILES_PATH not set. Output lists will not have prefixes.")

    bench_files = list_bench_json_files()
    if not bench_files:
        print(f"No benchmark JSON files found in: {BENCH_DIR}")
        return

    lines_txt: List[str] = []
    lines_tsv: List[str] = [
        "batch_id\thostname\tpartition\tjob_id\telapsed_hms\tdone\ttotal\tfailed\tbatch_json_path\n"
    ]
    finished_smiles_set = set()
    failed_smiles_set = set()
    total_elapsed_seconds = 0

    for bf in bench_files:
        try:
            data = load_json(bf)
            batch_id = data.get("batch_id", "")
            hostname = data.get("hostname", "")
            partition = (data.get("slurm") or {}).get("partition", "")
            job_id = (data.get("slurm") or {}).get("job_id", "")
            elapsed_hms = data.get("elapsed_hms", "")
            counts = data.get("counts") or {}
            done = counts.get("done", 0)
            total = counts.get("total", 0)
            failed = counts.get("failed", 0)
            batch_json_path = data.get("batch_json_path", "")

            total_elapsed_seconds += parse_hms_to_seconds(elapsed_hms)

            lines_txt.append(
                f"{hostname} finished {done}/{total} in {elapsed_hms} "
                f"[batch {batch_id}] partition={partition} jobid={job_id}"
            )
            lines_tsv.append(
                f"{batch_id}\t{hostname}\t{partition}\t{job_id}\t"
                f"{elapsed_hms}\t{done}\t{total}\t{failed}\t{batch_json_path}\n"
            )

            for smi in (data.get("completed_smiles", []) or []):
                smi = smi.strip()
                if smi:
                    finished_smiles_set.add(smi)

            for smi, status in (data.get("per_smiles_status") or {}).items():
                if status == "fail":
                    smi = smi.strip()
                    if smi:
                        failed_smiles_set.add(smi)

        except Exception as e:
            lines_txt.append(f"[ERROR] Failed to read {bf}: {e}")

    with open(SUMMARY_TXT, "w") as f:
        f.write("\n".join(lines_txt) + ("\n" if lines_txt else ""))

    with open(SUMMARY_TSV, "w") as f:
        f.writelines(lines_tsv)

    with open(FINISHED_SMILES_TXT, "w") as f:
        if finished_smiles_set:
            f.write("\n".join(sorted(finished_smiles_set)) + "\n")

    with open(FAILED_SMILES_TXT, "w") as f:
        if failed_smiles_set:
            for smi in sorted(failed_smiles_set):
                prefix = smiles_prefix_map.get(smi, "UNKNOWN_PREFIX")
                f.write(f"{smi} {prefix}\n")

    still_missing: List[str] = []
    if ORIGINAL_SMILES_PATH and smiles_prefix_map:
        all_original_smiles = set(smiles_prefix_map.keys())
        missing_set = all_original_smiles - finished_smiles_set - failed_smiles_set
        still_missing = sorted(list(missing_set))
        
        out_path = STILL_MISSING_OUT_PATH or STILL_MISSING_SMILES_TXT
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            
        with open(out_path, "w") as f:
            for smi in still_missing:
                prefix = smiles_prefix_map.get(smi, "UNKNOWN_PREFIX")
                f.write(f"{smi} {prefix}\n")

    total_finished = len(finished_smiles_set)
    total_missing = len(still_missing) if ORIGINAL_SMILES_PATH else 0
    total_elapsed_hms = seconds_to_hms(total_elapsed_seconds)
    per_mol_hms = seconds_to_hms(int(total_elapsed_seconds / total_finished)) if total_finished > 0 else "0:00:00"

    print(f"Wrote: {SUMMARY_TXT}")
    print(f"Wrote: {SUMMARY_TSV}")
    print(f"Wrote: {FINISHED_SMILES_TXT} (SMILES only)")
    print(f"Wrote: {FAILED_SMILES_TXT} (SMILES PREFIX)")
    if ORIGINAL_SMILES_PATH:
        print(f"Wrote: {STILL_MISSING_OUT_PATH or STILL_MISSING_SMILES_TXT} (SMILES PREFIX)")

    print(
        f"Finished {total_finished} unique SMILES in total {total_elapsed_hms}, "
        f"yielding {per_mol_hms} per molecule, with {total_missing} molecules still missing."
    )
