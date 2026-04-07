#!/bin/bash

# activate a correct anaconda environment
module load anaconda/2022.10-py39
#source activate /scratch/negishi/li1724/100624_copy_yarp/
conda activate copy-classy-yarp
#conda activate IOP
module load intel-mkl
module load openmpi

# --- Configuration ---
# File containing the absolute paths to the *full job directories*
# (e.g., .../TS-GAT-CyXant-ax-sm_0_2), one per line.
# You can point this to Example_crashed.txt or another list.
CRASHED_LIST_FILE="crashed.txt"

# SLURM account/partition name base (kept for completeness;
# queue change is applied directly to the job template content below)
SLURM_ACCOUNT="normal"

# A unique name for this batch of jobs to track them in the queue
BATCHNAME="AAAS"

# The maximum number of jobs from this batch to have in the queue at one time
JOB_LIMIT=200

# How many seconds to wait before re-checking the queue when the limit is reached
CHECK_EVERY=30

# --- Script Body ---
if [ ! -f "$CRASHED_LIST_FILE" ]; then
    echo "Error: Crashed jobs file not found at '$CRASHED_LIST_FILE'"
    exit 1
fi

echo "Starting restart workflow from '$CRASHED_LIST_FILE'..."
echo "Job limit: ${JOB_LIMIT} for batch '${BATCHNAME}'."

while IFS= read -r FULL_DIR_PATH || [[ -n "$FULL_DIR_PATH" ]]; do
    if [ -z "$FULL_DIR_PATH" ]; then
        continue
    fi

    echo "Processing crashed job: $FULL_DIR_PATH"

    # The crashed archive is expected to be FULL_DIR_PATH + '-crashed.zip'
    CRASHED_ZIP="${FULL_DIR_PATH}-crashed.zip"

    # If a final non-crashed zip already exists, we can skip this job
    if [ -f "${FULL_DIR_PATH}.zip" ]; then
        echo "  -> Skipping ${FULL_DIR_PATH}: final result zip already exists."
        continue
    fi

    # If the crashed zip doesn't exist, warn and skip
    if [ ! -f "$CRASHED_ZIP" ]; then
        echo "  -> WARNING: Crashed archive not found at '$CRASHED_ZIP'. Skipping."
        continue
    fi

    # --- Parse Charge, Multiplicity, and Base Path (same logic as untouched script) ---
    # Example FULL_DIR_PATH: /path/to/block/19_-1_2

    # Get multiplicity (e.g., "2")
    multiplicity=${FULL_DIR_PATH##*_}

    # Get path without multiplicity (e.g., "/path/to/block/19_-1")
    TEMP_PATH=${FULL_DIR_PATH%_${multiplicity}}

    # Get charge (e.g., "-1")
    charge=${TEMP_PATH##*_}

    # Get the original base path (e.g., "/path/to/block/19")
    PATH_NO_SLASH=${TEMP_PATH%_${charge}}

    # Get the path to the original XYZ file (e.g., "/path/to/block/19.xyz")
    XYZ_FILE_PATH="${PATH_NO_SLASH}.xyz"

    # --- Validation ---
    if [ -z "$charge" ] || [ -z "$multiplicity" ]; then
        echo "  -> ERROR: Could not parse charge/multiplicity from '$FULL_DIR_PATH'. Skipping."
        continue
    fi

    if [ ! -f "$XYZ_FILE_PATH" ]; then
        echo "  -> ERROR: Original input file not found: '$XYZ_FILE_PATH'. Skipping."
        continue
    fi

    # --- Job Name Generation (from original script) ---
    # Extract the index from the path using a regex.
    index=$(echo "$PATH_NO_SLASH" | grep -oP '(?:/All-XYZ|/all-pdf-xyz)/\K[^/]+')

    if [ -z "$index" ]; then
        echo "  -> WARNING: Could not extract index for path: $PATH_NO_SLASH. Using 'NA' for index."
        index="NA"
    fi

    # Extract the block name (parent directory of the .xyz file)
    block=$(basename "$(dirname "$XYZ_FILE_PATH")")
    BASENAME=$(basename "$XYZ_FILE_PATH" .xyz)

    # Construct the job name (same pattern as untouched)
    JOB_NAME="${BATCHNAME}-${index}-${block}-${BASENAME}-${charge}"

    # --- Job Status Checks (similar to original script) ---
    # If a job with the same name is already in the queue, skip
    if squeue -u "$USER" --noheader -o "%.200j" | grep -q "${JOB_NAME}$"; then
        echo "  -> Skipping ${FULL_DIR_PATH}: Job is already in the SLURM queue."
        continue
    fi

    # Remove stale working directory if present
    if [ -d "${FULL_DIR_PATH}" ]; then
        echo "  -> Found stale directory for ${FULL_DIR_PATH}. Cleaning up."
        rm -rf "${FULL_DIR_PATH}"
    fi

    # Remove the old crashed archive before restarting
    echo "  -> Removing old crashed archive: ${CRASHED_ZIP}"
    rm -f "${CRASHED_ZIP}"

    # --- Job Limit and Submission Logic (same "below-limit" scheduler) ---
    while true; do
        current_jobs=$(squeue -u "$USER" -h -o "%j" | grep -F "$BATCHNAME" | wc -l)

        if (( current_jobs < JOB_LIMIT )); then
            echo "  --> Preparing and submitting LONG job for ${FULL_DIR_PATH}. Current jobs: ${current_jobs}/${JOB_LIMIT}."

            mkdir -p "$FULL_DIR_PATH"
            cp "$XYZ_FILE_PATH" "${FULL_DIR_PATH}/input.xyz"

            # Use the parsed charge and multiplicity to fill templates
            sed -e "s/CHARGE_PLACEHOLDER/${charge}/g" -e "s/MULT_PLACEHOLDER/${multiplicity}/g" TSOPT.yaml.template > "${FULL_DIR_PATH}/TSOPT.yaml"
            sed -e "s/CHARGE_PLACEHOLDER/${charge}/g" -e "s/MULT_PLACEHOLDER/${multiplicity}/g" TSOPT-IRC.yaml.template > "${FULL_DIR_PATH}/TSOPT-IRC.yaml"

            # Read the job template and customize it
            template_content=$(<job_tsopt.submit.template)

            # Fill in the usual placeholders
            modified_content="${template_content//XXX/${BASENAME}}"
            modified_content="${modified_content//CHARGE_PLACEHOLDER/${charge}}"
            modified_content="${modified_content//JOBNAME_PLACEHOLDER/${JOB_NAME}}"

            # --- Make the rerun long: change queue + walltime ---
            # Replace standby queue with normal
            modified_content="${modified_content//standby/normal}"

            # Replace 04-hour walltime with 168 hours (7 days)
            # Assumes original template uses 04:00:00
            modified_content="${modified_content//04:00:00/168:00:00}"

            echo "$modified_content" > "${FULL_DIR_PATH}/job_tsopt.submit"

            (cd "$FULL_DIR_PATH" && sbatch job_tsopt.submit)

            # The job_tsopt.submit template is responsible for zipping the
            # finished run into "${FULL_DIR_PATH}.zip" (without "-crashed").
            break  # Job submitted, exit the inner while-true loop
        else
            printf '[%s] Job limit reached. %d jobs in queue (limit %d). Waiting %ds...\n' \
                   "$(date '+%H:%M:%S')" "$current_jobs" "$JOB_LIMIT" "$CHECK_EVERY"
            sleep "$CHECK_EVERY"
        fi
    done

done < "$CRASHED_LIST_FILE"

echo "Workflow finished. All crashed jobs in '$CRASHED_LIST_FILE' have been (re)submitted."
