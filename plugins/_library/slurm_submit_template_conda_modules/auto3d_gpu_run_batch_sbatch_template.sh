# ── SNIPPET: slurm_submit_template_conda_modules/auto3d_gpu_run_batch_sbatch_template ─
# Scheduler:   slurm
# Tool:        auto3d
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: queue/partition list is cluster-specific; keep as placeholders when porting.
# ────────────────────────────────────────────────────────────

import os

def write_gpu_sub_file(batch_idx: int, batch_json_path: str, queue: str, qos: str, time_h: int, gpus: int, auto_batch_size: int) -> str:
    ensure_dir(GPU_SUBMISSIONS_DIR)
    script_path = os.path.join(GPU_SUBMISSIONS_DIR, f"auto3d_gpu_batch_{batch_idx}.sub")

    sub_lines = [
        "#!/bin/bash",
        "#SBATCH -A bsavoie",
        "#SBATCH --nodes=1",
        "#SBATCH --gpus-per-node=1",
        "#SBATCH --cpus-per-gpu=10",
        "#SBATCH --mem=100G",
        "#SBATCH -t 4:00:00",
        "#SBATCH --partition=a100-80gb,a100-40gb,a30,a10,h100",
        "#SBATCH --qos=standby",
        f"#SBATCH --job-name=auto3d_{batch_idx}",
        f"#SBATCH --error=auto3d_gpu_batch_{batch_idx}.err",
        f"#SBATCH --output=auto3d_gpu_batch_{batch_idx}.out",
        "",
        "# module --force purge",
        "module load conda",
        f"conda activate {CONDA_ENV}",
        "",
        "cd $SLURM_SUBMIT_DIR",
        f"cd {THIS_SCRIPT_DIR}",
        f"python -u {os.path.basename(__file__)} run-batch {batch_json_path} --procs 1 --auto-batch-size {auto_batch_size}",
        "cd $SLURM_SUBMIT_DIR",
        "",
    ]
    with open(script_path, "w") as f:
        f.write("\n".join(sub_lines))
    return script_path
