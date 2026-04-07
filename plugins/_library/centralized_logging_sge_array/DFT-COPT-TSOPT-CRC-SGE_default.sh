# ── SNIPPET: centralized_logging_sge_array/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   sge
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Redirect must happen early so all output is captured.
#   - Log filenames include SGE_TASK_ID to avoid collisions.
# Notes: Create logs dir before exec redirection.
# ────────────────────────────────────────────────────────────

LOGS_DIR="{{PIPELINE_DIR}}/logs"

# Create logs directory
mkdir -p "${LOGS_DIR}"

# Redirect output to pipeline logs directory
exec 1>"${LOGS_DIR}/dft_${SGE_TASK_ID}.out" 2>"${LOGS_DIR}/dft_${SGE_TASK_ID}.err"
