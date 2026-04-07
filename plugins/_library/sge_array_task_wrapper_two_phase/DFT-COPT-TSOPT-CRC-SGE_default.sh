# ── SNIPPET: sge_array_task_wrapper_two_phase/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   sge
# Tool:        singularity
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Must be submitted from pipeline directory so SGE_O_WORKDIR points to correct tree.
#   - Fail fast if required per-job inputs missing (R.xyz/P.xyz/TS.xyz/config.json).
#   - Two-phase execution: preprocessing must create workflow_status.json before tarball packaging.
#   - Charge/mult read from per-job config.json and passed into preprocessing.
# Notes: Full tested script body.
# ────────────────────────────────────────────────────────────

#!/bin/bash
#$ -N dft_verify
#$ -cwd
#$ -pe smp 16
#$ -l h_rt=72:00:00
#$ -t 1-10
# =============================================================================
# SGE DFT Verification Pipeline
# =============================================================================
# Uses container's native run_dft_workflow.sh (sets up ORCA env) with
# bind-mounted custom run_dft_verification.py (has config file support)
# 
# IMPORTANT: Submit from the pipeline directory!
#   cd /path/to/dft_test_pipeline
#   qsub sge_dft_pipeline.sh
# =============================================================================

# ============== CONFIGURATION ==============
CONTAINER_IMAGE="{{CONTAINER_IMAGE}}"
PIPELINE_DIR="${SGE_O_WORKDIR}"
# ===========================================

JOBS_DIR="${PIPELINE_DIR}/jobs"
JOB_LIST="${PIPELINE_DIR}/job_list.txt"
SCRIPTS_DIR="${PIPELINE_DIR}/scripts"
LOGS_DIR="${PIPELINE_DIR}/logs"

# Create logs directory
mkdir -p "${LOGS_DIR}"

# Redirect output to pipeline logs directory
exec 1>"${LOGS_DIR}/dft_${SGE_TASK_ID}.out" 2>"${LOGS_DIR}/dft_${SGE_TASK_ID}.err"

echo "=============================================="
echo "DFT Verification Job"
echo "=============================================="
echo "Task ID:      ${SGE_TASK_ID}"
echo "Pipeline dir: ${PIPELINE_DIR}"
echo "Start time:   $(date)"
echo "Host:         $(hostname)"
echo "Slots:        ${NSLOTS:-16}"
echo "=============================================="

# Check job list exists
if [ ! -f "$JOB_LIST" ]; then
    echo "ERROR: Job list not found: $JOB_LIST"
    exit 1
fi

# Get job name from list
JOB_NAME=$(sed -n "${SGE_TASK_ID}p" "$JOB_LIST")

if [ -z "$JOB_NAME" ]; then
    echo "ERROR: No job found for task ID ${SGE_TASK_ID}"
    exit 1
fi

JOB_DIR="${JOBS_DIR}/${JOB_NAME}"
OUTPUT_DIR="${JOB_DIR}/output"

echo "Job Name:     ${JOB_NAME}"
echo "Job Dir:      ${JOB_DIR}"
echo "Output Dir:   ${OUTPUT_DIR}"
echo "=============================================="

# Check job directory exists
if [ ! -d "$JOB_DIR" ]; then
    echo "ERROR: Job directory not found: $JOB_DIR"
    exit 1
fi

# Check required files
for f in R.xyz P.xyz TS.xyz config.json; do
    if [ ! -f "${JOB_DIR}/${f}" ]; then
        echo "ERROR: Required file not found: ${JOB_DIR}/${f}"
        exit 1
    fi
done

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Read charge and mult from config.json
CHARGE=$(python3 -c "import json; print(json.load(open('${JOB_DIR}/config.json'))['charge'])")
MULT=$(python3 -c "import json; print(json.load(open('${JOB_DIR}/config.json'))['mult'])")

echo "Charge: ${CHARGE}"
echo "Mult:   ${MULT}"

# =============================================================================
# STEP 1: Run preprocessing to compute BEM and create workflow_status.json
# =============================================================================
echo
echo "Step 1: Preprocessing (BEM computation)..."
echo

singularity exec \
    -B "${JOB_DIR}:/work/input:ro" \
    -B "${OUTPUT_DIR}:/work/output" \
    -B "${SCRIPTS_DIR}:/work/scripts:ro" \
    -B /opt/sge:/opt/sge \
    "${CONTAINER_IMAGE}" \
    python /work/scripts/xyz_prep.py \
        --reactant /work/input/R.xyz \
        --product /work/input/P.xyz \
        --ts /work/input/TS.xyz \
        --charge ${CHARGE} \
        --mult ${MULT} \
        --output /work/output \
        --prep-only

PREP_EXIT=$?
if [ $PREP_EXIT -ne 0 ]; then
    echo "ERROR: Preprocessing failed with exit code $PREP_EXIT"
    exit $PREP_EXIT
fi

# Check workflow_status.json was created
if [ ! -f "${OUTPUT_DIR}/workflow_status.json" ]; then
    echo "ERROR: workflow_status.json was not created"
    exit 1
fi

echo "Preprocessing complete."
echo "Bond changes detected:"
python3 -c "import json; ws=json.load(open('${OUTPUT_DIR}/workflow_status.json')); print(ws['input_data'].get('bond_changes', 'N/A'))"

# =============================================================================
# STEP 2: Create results.tar.gz for container's workflow
# =============================================================================
echo
echo "Step 2: Creating input tar.gz..."
echo

# Copy required files to output directory
cp "${JOB_DIR}/config.json" "${OUTPUT_DIR}/config.json"
cp "${JOB_DIR}/R.xyz" "${OUTPUT_DIR}/R.xyz"
cp "${JOB_DIR}/P.xyz" "${OUTPUT_DIR}/P.xyz"

cd "${OUTPUT_DIR}"
tar -czvf results.tar.gz ts_guess.xyz workflow_status.json R.xyz P.xyz config.json

if [ ! -f "${OUTPUT_DIR}/results.tar.gz" ]; then
    echo "ERROR: Failed to create results.tar.gz"
    exit 1
fi

echo "Created: results.tar.gz ($(ls -lh results.tar.gz | awk '{print $5}'))"

# =============================================================================
# STEP 3: Run DFT workflow using container's native shell script
#         with bind-mounted custom run_dft_verification.py
# =============================================================================
echo
echo "Step 3: Running DFT workflow..."
echo "Container: ${CONTAINER_IMAGE}"
echo "Using custom run_dft_verification.py with config support"
echo

singularity exec \
    -B "${OUTPUT_DIR}:/work" \
    -B "${SCRIPTS_DIR}/run_dft_verification.py:/opt/dft_workflow/run_dft_verification.py:ro" \
    -B /opt/sge:/opt/sge \
    --pwd /work \
    "${CONTAINER_IMAGE}" \
    /opt/dft_workflow/run_dft_workflow.sh \
    --mode full \
    --input "/work/results.tar.gz" \
    --output /work \
    --nprocs ${NSLOTS:-16} \
    --maxcore 4000 \
    --config /work/config.json

EXIT_CODE=$?

echo
echo "=============================================="
echo "Job completed"
echo "=============================================="
echo "Exit code:  ${EXIT_CODE}"
echo "End time:   $(date)"
echo "=============================================="

# Copy final status to job directory
if [ -f "${OUTPUT_DIR}/workflow_status.json" ]; then
    cp "${OUTPUT_DIR}/workflow_status.json" "${JOB_DIR}/final_status.json"
    echo "Final status saved to: ${JOB_DIR}/final_status.json"
fi

exit $EXIT_CODE
