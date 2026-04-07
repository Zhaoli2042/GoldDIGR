# ── SNIPPET: slurm_submit_throttle_by_batchtag/htcondor_throttle_by_queue_size_chunk_dripfeed ─
# Scheduler:   htcondor
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Notes: Uses condor_q parsing heuristics; keep as-is for tested behavior.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: monitor_submit.sh

MAX_JOBS={{MAX_JOBS}}
USER_ID="${USER}"
CHECK_INTERVAL={{CHECK_INTERVAL_SECONDS}}
SUBMIT_FILE="{{SUBMIT_FILE}}"
FILE_PATTERN="{{CHUNK_GLOB}}"

echo "=============================================="
echo "DFT Energy — Job Submission Monitor"
echo "=============================================="
echo "Submit file:    $SUBMIT_FILE"
echo "File pattern:   $FILE_PATTERN"
echo "Max jobs:       $MAX_JOBS"
echo "User:           $USER_ID"
echo "Check interval: ${CHECK_INTERVAL}s"
echo ""

mkdir -p submitted_batches

get_job_count() {
    local count
    count=$(condor_q "$USER_ID" 2>/dev/null | grep "Total for query" | awk '{print $4}')

    if [ -z "$count" ]; then
        count=$(condor_q "$USER_ID" 2>/dev/null | awk -v user="$USER_ID" '$0 ~ user {sum += $10} END {print sum+0}')
    fi

    echo "${count:-0}"
}

if [ ! -f "$SUBMIT_FILE" ]; then
    echo "Error: Submit file not found: $SUBMIT_FILE"
    exit 1
fi

PENDING_FILES=$(ls $FILE_PATTERN 2>/dev/null | wc -l)
if [ "$PENDING_FILES" -eq 0 ]; then
    echo "Error: No job files found matching $FILE_PATTERN"
    exit 1
fi
echo "Job files to submit: $PENDING_FILES"
echo ""

for batch_file in $(ls $FILE_PATTERN 2>/dev/null | sort -t_ -k2 -n); do
    [ -f "$batch_file" ] || continue

    if [ -f "submitted_batches/$batch_file" ]; then
        echo "Skipping $batch_file (already submitted)"
        continue
    fi

    while true; do
        current_jobs=$(get_job_count)

        echo "[$(date '+%H:%M:%S')] Queue: $current_jobs / $MAX_JOBS jobs"

        if [ "$current_jobs" -lt "$MAX_JOBS" ]; then
            echo "   -> Queue has capacity. Submitting..."
            break
        else
            echo "   -> Queue full. Waiting $((CHECK_INTERVAL / 60)) minutes..."
            sleep $CHECK_INTERVAL
        fi
    done

    echo ""
    echo "=============================================="
    echo "Submitting: $batch_file"
    echo "=============================================="

    JOB_COUNT=$(wc -l < "$batch_file")
    echo "Jobs in file: $JOB_COUNT"

    condor_submit "$SUBMIT_FILE" input_list="$batch_file"
    SUBMIT_EXIT=$?

    if [ $SUBMIT_EXIT -eq 0 ]; then
        mv "$batch_file" submitted_batches/
        echo "Moved $batch_file to submitted_batches/"
    else
        echo "Warning: condor_submit returned exit code $SUBMIT_EXIT"
        echo "Will retry $batch_file on next cycle"
        sleep 60
        continue
    fi

    echo ""
    sleep 10
done
