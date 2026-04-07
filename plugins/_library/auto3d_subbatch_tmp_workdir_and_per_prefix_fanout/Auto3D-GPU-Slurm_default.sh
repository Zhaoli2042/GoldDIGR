# ── SNIPPET: auto3d_subbatch_tmp_workdir_and_per_prefix_fanout/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        auto3d
# Tested:      purdue_standby_auto3d_auto_batch
# Invariants:
#   - Batch dict value must be 'out_path:::prefix' using BATCH_DICT_SEPARATOR.
#   - Writes input file 'smi.smi' with lines 'SMILES PREFIX' so SDF titles match PREFIX.
#   - Uses first molecule's out_path as shared target_dir for all outputs in the subbatch.
#   - Fans out multi-record SDF by matching record title == PREFIX.
#   - Always writes {PREFIX}.smi even if SDF record missing.
# Notes: This is the per-job execution wrapper logic (compute-node task wrapper).
# ────────────────────────────────────────────────────────────

import os
import shutil
import time
from typing import Dict, List, Tuple

def run_auto3d_for_smiles_subbatch(subbatch: List[Tuple[str, str]], use_gpu: bool = True) -> Dict[str, bool]:
    """
    Run Auto3D once for a subbatch of SMILES.
    subbatch: list of (smiles, val) tuples where val is "out_path:::prefix"
    Returns: map smiles -> success(bool)
    """
    status_map: Dict[str, bool] = {s: False for s, _ in subbatch}
    if not _AUTO3D_AVAILABLE:
        for s, _ in subbatch:
            print(f"[WARN] Auto3D not available in this environment. Skipping {s}")
        return status_map

    parsed_items = []
    for smiles, val in subbatch:
        if BATCH_DICT_SEPARATOR in val:
            path, prefix = val.split(BATCH_DICT_SEPARATOR, 1)
        else:
            path, prefix = val, "MOL_UNKNOWN"
        parsed_items.append((smiles, path, prefix))

    first_out_abs = os.path.abspath(parsed_items[0][1])

    try:
        tmp_base = os.path.join(first_out_abs, "_auto3d_batch_tmp")
        ensure_dir(tmp_base)
        tmp_dir = os.path.join(tmp_base, f"batch_{int(time.time())}_{os.getpid()}_{len(subbatch)}")
        ensure_dir(tmp_dir)

        prev_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            label_to_entry: Dict[str, Tuple[str, str]] = {}
            with open("smi.smi", "w") as f:
                for (smiles, out_path, prefix) in parsed_items:
                    label_to_entry[prefix] = (smiles, out_path)
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

            candidates = []
            if out_sdf_path:
                out_sdf_abs = os.path.abspath(out_sdf_path)
                if os.path.exists(out_sdf_abs) and out_sdf_abs.endswith(".sdf"):
                    candidates.append(out_sdf_abs)
            candidate_sdf_abs = os.path.abspath("smi_auto3d_geo_opt/smi_out.sdf")
            if os.path.exists(candidate_sdf_abs):
                candidates.append(candidate_sdf_abs)

            if not candidates:
                print("[WARN] No SDF produced by Auto3D for subbatch.")
                return status_map

            sdf_path = candidates[0]
            records = _split_sdf_records_by_title(sdf_path)
            label_to_record: Dict[str, List[str]] = {title: rec_lines for title, rec_lines in records}

            target_dir = first_out_abs
            ensure_dir(target_dir)

            try:
                shutil.copy2("smi.smi", os.path.join(target_dir, "smi.smi"))
            except Exception:
                pass
            try_copy_auto3d_log_from_sdf_dir(sdf_path, target_dir)

            for prefix, (smiles, _) in label_to_entry.items():
                rec_lines = label_to_record.get(prefix, [])

                label_sdf_path = os.path.join(target_dir, f"{prefix}.sdf")
                label_smi_path = os.path.join(target_dir, f"{prefix}.smi")

                if rec_lines:
                    with open(label_sdf_path, "w") as df:
                        df.writelines(rec_lines)
                    status_map[smiles] = os.path.exists(label_sdf_path)
                else:
                    status_map[smiles] = False

                with open(label_smi_path, "w") as sf:
                    sf.write(f"{smiles} {prefix}\n")

            try:
                encoded_sdf_src = os.path.abspath(os.path.join("smi_auto3d_geo_opt", "job1", "smi_encoded_1_3d.sdf"))
                if os.path.exists(encoded_sdf_src):
                    write_file(encoded_sdf_src, os.path.join(target_dir, "smi_encoded_1_3d.sdf"))
            except Exception:
                pass
        finally:
            os.chdir(prev_cwd)

        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            try:
                os.rmdir(tmp_base)
            except Exception:
                pass
        except Exception:
            pass

        return status_map
    except Exception as e:
        print(f"[ERROR] Auto3D subbatch failed. Error: {e}")
        return status_map
