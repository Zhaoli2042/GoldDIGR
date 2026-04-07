# ── SNIPPET: htcondor_submit_file_transfer_and_remap/singularity_bind_ro_inputs_rw_outputs_split_workdirs ─
# Scheduler:   any
# Tool:        singularity
# Tested:      {{PLUGIN_NAME}}
# Notes: Used for preprocessing step.
# ────────────────────────────────────────────────────────────

singularity exec \
    -B "{{JOB_DIR}}:/work/input:ro" \
    -B "{{OUTPUT_DIR}}:/work/output" \
    -B "{{SCRIPTS_DIR}}:/work/scripts:ro" \
    -B /opt/sge:/opt/sge \
    "{{CONTAINER_IMAGE}}" \
    python /work/scripts/xyz_prep.py \
        --reactant /work/input/R.xyz \
        --product /work/input/P.xyz \
        --ts /work/input/TS.xyz \
        --charge {{CHARGE}} \
        --mult {{MULT}} \
        --output /work/output \
        --prep-only
