#!/bin/bash
#SBATCH --job-name=extract_energies_array
#SBATCH --output=full_scan_chunks/slurm_logs/chunk_%A_%a.out
#SBATCH --error=full_scan_chunks/slurm_logs/chunk_%A_%a.err
#SBATCH -A bsavoie
#SBATCH --partition=cpu
#SBATCH --qos=standby
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=00:30:00
#SBATCH --array=1-100%20

set -euo pipefail

WORKDIR=/scratch/negishi/li1724/SI-Downloads/SI_Agent/051926-DFT-Calcs/missing_DFT_zips_finished_first
SCRIPT="$WORKDIR/extract_energies.py"
ZIP_DIR=/scratch/negishi/li1724/SI-Downloads/SI_Agent/doi_zips
CHUNKDIR="$WORKDIR/full_scan_chunks"

IDX=$(printf "%03d" "$SLURM_ARRAY_TASK_ID")
KEYS="$CHUNKDIR/chunk_${IDX}.txt"
OUT="$CHUNKDIR/energies_chunk_${IDX}.csv"

echo "Array task: $SLURM_ARRAY_TASK_ID  Job: $SLURM_JOB_ID  Node: $(hostname)"
echo "CPUs:       $SLURM_CPUS_PER_TASK"
echo "Chunk:      $KEYS  ($(wc -l < "$KEYS") keys)"
echo "Output:     $OUT"
echo "Start:      $(date)"
echo

python3 "$SCRIPT" \
    --keys "$KEYS" \
    --zip-dir "$ZIP_DIR" \
    -o "$OUT" \
    -j "$SLURM_CPUS_PER_TASK"

echo
echo "Rows written: $(($(wc -l < "$OUT") - 1))"
echo "End:        $(date)"
