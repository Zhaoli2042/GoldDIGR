# ── SNIPPET: final_status_promotion/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Copy only if workflow_status.json exists; do not fail job on missing status.
# Notes: Enables status_file_fallback.
# ────────────────────────────────────────────────────────────

if [ -f "{{OUTPUT_DIR}}/workflow_status.json" ]; then
    cp "{{OUTPUT_DIR}}/workflow_status.json" "{{JOB_DIR}}/final_status.json"
    echo "Final status saved to: {{JOB_DIR}}/final_status.json"
fi
