# ── SNIPPET: auto3d_log_discovery_and_copy/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        auto3d
# Tested:      purdue_standby_auto3d_auto_batch
# Invariants:
#   - Checks sibling of sdf_path first: dirname(sdf_path)/Auto3D.log.
#   - Fallback path 'smi_auto3d_geo_opt/Auto3D.log' is assumed relative to current working directory.
# Notes: Keeps provenance for debugging and audit.
# ────────────────────────────────────────────────────────────

import os

def try_copy_auto3d_log_from_sdf_dir(sdf_path: str, results_dir: str) -> None:
    candidate = os.path.join(os.path.dirname(sdf_path), "Auto3D.log")
    if os.path.exists(candidate):
        write_file(candidate, os.path.join(results_dir, "Auto3D.log"))
        return
    if os.path.exists("smi_auto3d_geo_opt/Auto3D.log"):
        write_file("smi_auto3d_geo_opt/Auto3D.log", os.path.join(results_dir, "Auto3D.log"))
