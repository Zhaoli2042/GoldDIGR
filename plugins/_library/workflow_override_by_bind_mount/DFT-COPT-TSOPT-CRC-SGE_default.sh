# ── SNIPPET: workflow_override_by_bind_mount/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        singularity
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Bind-mount target path must exactly match the container’s import/entrypoint path.
#   - Mount override read-only to prevent container writes to host code.
# Notes: Used to add config support without rebuilding the SIF.
# ────────────────────────────────────────────────────────────

singularity exec \
    -B "{{OUTPUT_DIR}}:/work" \
    -B "{{SCRIPTS_DIR}}/run_dft_verification.py:/opt/dft_workflow/run_dft_verification.py:ro" \
    -B /opt/sge:/opt/sge \
    --pwd /work \
    "{{CONTAINER_IMAGE}}" \
    /opt/dft_workflow/run_dft_workflow.sh \
    --mode full \
    --input "/work/results.tar.gz" \
    --output /work \
    --nprocs {{NPROCS}} \
    --maxcore {{MAXCORE}} \
    --config /work/config.json
