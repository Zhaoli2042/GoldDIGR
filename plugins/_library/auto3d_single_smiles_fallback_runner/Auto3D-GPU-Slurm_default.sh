# ── SNIPPET: auto3d_single_smiles_fallback_runner/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        auto3d
# Tested:      purdue_standby_auto3d_auto_batch
# Invariants:
#   - Batch dict value must be 'out_path:::prefix' (or prefix defaults to MOL_UNKNOWN).
#   - Writes smi.smi with 'SMILES PREFIX' and expects Auto3D to produce an SDF.
#   - Final output is named {PREFIX}.sdf.
# Notes: Useful when subbatching is disabled or for debugging.
# ────────────────────────────────────────────────────────────

import os

def run_auto3d_for_single_smiles(smiles: str, val: str, use_gpu: bool = True) -> bool:
    if not _AUTO3D_AVAILABLE:
        print(f"[WARN] Auto3D not available in this environment. Skipping {smiles}")
        return False

    if BATCH_DICT_SEPARATOR in val:
        out_path, prefix = val.split(BATCH_DICT_SEPARATOR, 1)
    else:
        out_path, prefix = val, "MOL_UNKNOWN"

    try:
        out_path_abs = os.path.abspath(out_path)
        ensure_dir(out_path_abs)
        results_dir = os.path.join(out_path_abs, "results")
        ensure_dir(results_dir)

        prev_cwd = os.getcwd()
        os.chdir(out_path_abs)

        try:
            with open("smi.smi", "w") as f:
                f.write(f"{smiles} {prefix}\n")

            args_auto3d = auto3d_options(
                "smi.smi",
                k=1,
                memory=64,
                verbose=False,
                enumerate_tautomer=False,
                enumerate_isomer=True,
                mpi_np=10,
                optimizing_engine="AIMNET",
                use_gpu=use_gpu,
                job_name="auto3d_geo_opt",
            )
            out_sdf_path = auto3d_main(args_auto3d)

            sdf_src = os.path.abspath(out_sdf_path) if out_sdf_path else ""
            final_sdf_name = f"{prefix}.sdf"

            if sdf_src and os.path.exists(sdf_src):
                write_file(sdf_src, os.path.join(results_dir, final_sdf_name))
            else:
                candidate_sdf_abs = os.path.abspath("smi_auto3d_geo_opt/smi_out.sdf")
                if os.path.exists(candidate_sdf_abs):
                    write_file(candidate_sdf_abs, os.path.join(results_dir, final_sdf_name))

            try_copy_auto3d_log_from_sdf_dir(sdf_src or "", results_dir)
            write_file("smi.smi", os.path.join(results_dir, "smi.smi"))
        finally:
            os.chdir(prev_cwd)

        return os.path.exists(os.path.join(results_dir, f"{prefix}.sdf"))
    except Exception as e:
        print(f"[ERROR] Auto3D failed for SMILES: {smiles}. Error: {e}")
        return False
