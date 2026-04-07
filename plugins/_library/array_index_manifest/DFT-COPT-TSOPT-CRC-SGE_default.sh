# ── SNIPPET: array_index_manifest/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   sge
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - job_list.txt line N corresponds to task ID N; selection via sed -n '${SGE_TASK_ID}p'.
# Notes: Extracted from sge_dft_pipeline.sh.
# ────────────────────────────────────────────────────────────

JOB_LIST="{{PIPELINE_DIR}}/job_list.txt"

# Get job name from list
JOB_NAME=$(sed -n "${SGE_TASK_ID}p" "$JOB_LIST")

if [ -z "$JOB_NAME" ]; then
    echo "ERROR: No job found for task ID ${SGE_TASK_ID}"
    exit 1
fi
