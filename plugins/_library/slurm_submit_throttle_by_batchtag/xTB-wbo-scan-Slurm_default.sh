# ── SNIPPET: slurm_submit_throttle_by_batchtag/xTB-wbo-scan-Slurm_default ─
# Scheduler:   slurm
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Throttle is implemented by counting squeue job names containing the batch tag.
#   - Sleep-and-retry loop continues until below limit.
#   - Duplicate submission is avoided by exact job-name match in squeue output.
# Notes: Includes zip gating and template materialization as used in the workflow.
# ────────────────────────────────────────────────────────────

#!/bin/bash

# ---------------- Configuration ----------------

# File listing finished calculation folders (TS-level dirs), one per line
FINISHED_LIST_FILE="{{FINISHED_LIST_FILE}}"

# SLURM batch tag for these jobs (used to monitor queue)
BATCHNAME="{{BATCHNAME}}"

# Max number of jobs with this batch tag in the queue at once
JOB_LIMIT={{JOB_LIMIT}}

# How many seconds to wait before re-checking the queue when limit is reached
CHECK_EVERY={{CHECK_EVERY}}

# Template for the spin-BO job (must be in the same directory as this script)
SUBMIT_TEMPLATE="{{SUBMIT_TEMPLATE}}"

# ---------------- Sanity checks ----------------

if [ ! -f "$FINISHED_LIST_FILE" ]; then
    echo "Error: Finished jobs file not found at '$FINISHED_LIST_FILE'"
    exit 1
fi

if [ ! -f "$SUBMIT_TEMPLATE" ]; then
    echo "Error: Submit template not found at '$SUBMIT_TEMPLATE'"
    exit 1
fi

echo "Starting spin-BO analysis submission from '$FINISHED_LIST_FILE'..."
echo "Job limit: ${JOB_LIMIT} for batch '${BATCHNAME}'."

SCRIPT_DIR=$(pwd)

# ---------------- Build unique parent folder list ----------------
PARENT_DIRS=$(
awk '{print $1}' "$FINISHED_LIST_FILE" |
while IFS= read -r path; do
    dirname -- "$path"
done | sort -u
)

# ---------------- Main loop over parent dirs ----------------------

for PARENT_DIR in $PARENT_DIRS; do
    [ -z "$PARENT_DIR" ] && continue

    echo "Processing parent folder: $PARENT_DIR"

    # ---- Check whether any zip in this parent folder still needs xTB-scan ----
    needs_job=false

    # Iterate over all .zip files (skip any with 'crash' in the name)
    shopt -s nullglob
    for zip_file in "$PARENT_DIR"/*.zip; do
        [[ "$zip_file" == *crash* ]] && continue

        # If the zip already contains xTB-scan/, it is fully processed → skip this zip
        if { unzip -l "$zip_file" || true; } | grep -q "xTB-scan/"; then
            continue
        fi

        # If the zip does NOT have xTB-scan/, but DOES have finished_irc.trj,
        # then this parent folder still has work to do.
        if { unzip -l "$zip_file" || true; } | grep -q "finished_irc.trj"; then
            echo "  -> Needs processing: $(basename "$zip_file") (has finished_irc.trj but no xTB-scan/)"
            needs_job=true
            break
        fi
    done
    shopt -u nullglob

    # If no zip in this folder needs processing, skip submitting a job for this parent directory
    if [ "$needs_job" != true ]; then
        echo "  -> All zip files either already have xTB-scan/ or lack finished_irc.trj; skipping parent folder."
        echo "---"
        continue
    fi

    # ---- Derive index and block for a nice job name ----
    index=$(echo "$PARENT_DIR" | grep -oP '(?:/All-XYZ|/all-pdf-xyz)/\K[^/]+')
    if [ -z "$index" ]; then
        echo "  -> WARNING: Could not extract index from '$PARENT_DIR'. Using 'NA'."
        index="NA"
    fi

    block=$(basename "$PARENT_DIR")

    JOB_NAME="${BATCHNAME}-${index}-${block}"

    # ---- Skip if job already in queue ----
    if squeue -u "$USER" --noheader -o "%.200j" | grep -q "${JOB_NAME}$"; then
        echo "  -> Skipping: Job '${JOB_NAME}' already in the SLURM queue."
        continue
    fi

    # ---- Job limit / queue throttling ----
    while true; do
        current_jobs=$(squeue -u "$USER" -h -o "%j" | grep -F "$BATCHNAME" | wc -l)

        if (( current_jobs < JOB_LIMIT )); then
            echo "  --> Preparing and submitting job for ${PARENT_DIR}. Current jobs: ${current_jobs}/${JOB_LIMIT}."

            # Create a unique submit script for this parent folder in the current directory
            submit_file="spin_bo.${index}_${block}.submit"

            template_content=$(<"$SUBMIT_TEMPLATE")
            # Fill in JOBNAME and FILEPATH placeholders
            modified_content="${template_content//JOBNAME_PLACEHOLDER/${JOB_NAME}}"
            modified_content="${modified_content//FILEPATH/${PARENT_DIR}}"

            printf '%s\n' "$modified_content" > "$submit_file"

            # Submit from the directory containing run_analysis.sh
            (cd "$SCRIPT_DIR" && sbatch "$submit_file")

            break
        else
            printf '[%s] Job limit reached. %d jobs in queue (limit %d). Waiting %ds...\n' \
                   "$(date '+%H:%M:%S')" "$current_jobs" "$JOB_LIMIT" "$CHECK_EVERY"
            sleep "$CHECK_EVERY"
        fi
    done

done

echo "All parent folders processed for submission."
