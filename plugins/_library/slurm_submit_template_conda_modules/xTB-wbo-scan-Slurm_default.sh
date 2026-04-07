# ── SNIPPET: slurm_submit_template_conda_modules/xTB-wbo-scan-Slurm_default ─
# Scheduler:   slurm
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - JOBNAME_PLACEHOLDER and FILEPATH placeholders must be replaced before submission.
#   - Assumes module system provides conda and required libs; analysis is invoked as ./run_analysis.sh FILEPATH.
# Notes: `run_analysis.sh` must exist alongside the submit script.
# ────────────────────────────────────────────────────────────

#!/bin/bash
#
#SBATCH --job-name=JOBNAME_PLACEHOLDER
#SBATCH --output=run_PLACEHOLDER.out
#SBATCH --error=run_PLACEHOLDER.err
#SBATCH -A bsavoie
#SBATCH --partition=cpu
#SBATCH --qos=standby
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --time 04:00:00

# Get the name of the directory this script is in (e.g., 03_-1_2)
DIR_NAME=$(basename "$PWD")

# Activate Conda environment 
module load conda/2025.02
conda activate another-yarp
module load intel-mkl
module load openmpi

./run_analysis.sh FILEPATH

wait
