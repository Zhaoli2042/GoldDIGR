# ── SNIPPET: result_packaging_tarball/single_handoff_results_tar_gz_for_container_consumption ─
# Scheduler:   any
# Tool:        tar
# Tested:      {{PLUGIN_NAME}}
# Notes: Matches container workflow’s --input contract.
# ────────────────────────────────────────────────────────────

# Copy required files to output directory
cp "{{JOB_DIR}}/config.json" "{{OUTPUT_DIR}}/config.json"
cp "{{JOB_DIR}}/R.xyz" "{{OUTPUT_DIR}}/R.xyz"
cp "{{JOB_DIR}}/P.xyz" "{{OUTPUT_DIR}}/P.xyz"

cd "{{OUTPUT_DIR}}"
tar -czvf results.tar.gz ts_guess.xyz workflow_status.json R.xyz P.xyz config.json

if [ ! -f "{{OUTPUT_DIR}}/results.tar.gz" ]; then
    echo "ERROR: Failed to create results.tar.gz"
    exit 1
fi
