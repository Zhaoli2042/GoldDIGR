#!/bin/bash
#SBATCH --job-name=extract_energies
#SBATCH --output=extract_energies_%j.out
#SBATCH --error=extract_energies_%j.err
#SBATCH -A bsavoie
#SBATCH --partition=cpu
#SBATCH --qos=standby
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=04:00:00

set -euo pipefail

SCRIPT=/scratch/negishi/li1724/SI-Downloads/SI_Agent/051926-DFT-Calcs/missing_DFT_zips_finished_first/extract_energies.py
KEYS=/scratch/negishi/li1724/SI-Downloads/SI_Agent/051926-DFT-Calcs/missing_DFT_zips_finished_first/four_class_keys.txt
ZIP_DIR=/scratch/negishi/li1724/SI-Downloads/SI_Agent/doi_zips
OUTPUT=/scratch/negishi/li1724/SI-Downloads/SI_Agent/051926-DFT-Calcs/missing_DFT_zips_finished_first/energies_${SLURM_JOB_ID}.csv

echo "Job:       $SLURM_JOB_ID on $(hostname)"
echo "CPUs:      $SLURM_CPUS_PER_TASK"
echo "Keys:      $(wc -l < "$KEYS") rows"
echo "Output:    $OUTPUT"
echo "Start:     $(date)"
echo

python3 "$SCRIPT" \
    --keys "$KEYS" \
    --zip-dir "$ZIP_DIR" \
    -o "$OUTPUT" \
    -j "$SLURM_CPUS_PER_TASK"

echo
echo "Rows written: $(($(wc -l < "$OUTPUT") - 1))"
echo "End:       $(date)"
