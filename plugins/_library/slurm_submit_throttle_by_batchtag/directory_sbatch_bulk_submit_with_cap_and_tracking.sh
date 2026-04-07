# ── SNIPPET: slurm_submit_throttle_by_batchtag/directory_sbatch_bulk_submit_with_cap_and_tracking ─
# Scheduler:   slurm
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: Uses os.system; assumes sbatch is on PATH.
# ────────────────────────────────────────────────────────────

import os
from typing import List

def submit_jobs(max_submit: int = 4900) -> List[str]:
    submitted: List[str] = []
    sub_files = sorted([f for f in os.listdir(GPU_SUBMISSIONS_DIR) if f.endswith(".sub")])
    for job in sub_files[:max_submit]:
        os.system(f"cd {GPU_SUBMISSIONS_DIR} && sbatch {job}")
        print(f"submitted {job}")
        submitted.append(job)
    with open("submitted_jobs_list_auto3d_gpu.txt", "w") as f:
        f.write("\n".join(submitted))
    return submitted
