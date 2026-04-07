# ── SNIPPET: smiles_prefix_parsing_and_batch_dict_generation/tsv_reaction_info_to_jobs_fanout_and_job_list ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Notes: This is the full tested script body (also includes cartesian product + inline JSON patch).
# ────────────────────────────────────────────────────────────

#!/bin/bash
# =============================================================================
# setup_jobs.sh - Prepare DFT verification jobs for SGE submission
# =============================================================================
# Usage: ./setup_jobs.sh
#
# This script:
# 1. Reads reaction info from reaction_info.txt
# 2. Creates job directories for each reaction × config combination
# 3. Copies XYZ files with standardized names
# 4. Creates per-job config files with charge/mult
# 5. Generates job list for SGE array submission
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIPELINE_DIR="${SCRIPT_DIR}"
TEST_DATA_DIR="${PIPELINE_DIR}/../Test-DFT"
JOBS_DIR="${PIPELINE_DIR}/jobs"
CONFIGS_DIR="${PIPELINE_DIR}/configs"
REACTION_INFO="${PIPELINE_DIR}/reaction_info.txt"

# Configs to test
CONFIGS=("original" "r2scan")

echo "=============================================="
echo "Setting up DFT verification jobs"
echo "=============================================="
echo "Pipeline dir: ${PIPELINE_DIR}"
echo "Test data:    ${TEST_DATA_DIR}"
echo "Jobs dir:     ${JOBS_DIR}"
echo

# Check directories exist
if [ ! -d "$TEST_DATA_DIR" ]; then
    echo "ERROR: Test data directory not found: $TEST_DATA_DIR"
    exit 1
fi

if [ ! -f "$REACTION_INFO" ]; then
    echo "ERROR: Reaction info file not found: $REACTION_INFO"
    exit 1
fi

# Clear and recreate jobs directory
rm -rf "${JOBS_DIR}"
mkdir -p "${JOBS_DIR}"

# Job counter
JOB_COUNT=0
JOB_LIST="${PIPELINE_DIR}/job_list.txt"
> "$JOB_LIST"

# Read reaction info (skip comments and empty lines)
while IFS=$'\t' read -r rxn_name charge mult; do
    # Skip comments and empty lines
    [[ "$rxn_name" =~ ^#.*$ ]] && continue
    [[ -z "$rxn_name" ]] && continue
    
    echo "Processing: $rxn_name (charge=$charge, mult=$mult)"
    
    # Check if reaction directory exists
    RXN_DIR="${TEST_DATA_DIR}/${rxn_name}"
    if [ ! -d "$RXN_DIR" ]; then
        echo "  WARNING: Reaction directory not found: $RXN_DIR"
        continue
    fi
    
    # Check for required XYZ files
    R_XYZ="${RXN_DIR}/finished_first.xyz"
    P_XYZ="${RXN_DIR}/finished_last.xyz"
    TS_XYZ="${RXN_DIR}/ts_final_geometry.xyz"
    
    if [ ! -f "$R_XYZ" ] || [ ! -f "$P_XYZ" ] || [ ! -f "$TS_XYZ" ]; then
        echo "  WARNING: Missing XYZ files in $RXN_DIR"
        continue
    fi
    
    # Create jobs for each config
    for config in "${CONFIGS[@]}"; do
        JOB_NAME="${rxn_name}_${config}"
        JOB_DIR="${JOBS_DIR}/${JOB_NAME}"
        
        echo "  Creating job: $JOB_NAME"
        
        mkdir -p "$JOB_DIR"
        
        # Copy XYZ files with standardized names
        cp "$R_XYZ" "${JOB_DIR}/R.xyz"
        cp "$P_XYZ" "${JOB_DIR}/P.xyz"
        cp "$TS_XYZ" "${JOB_DIR}/TS.xyz"
        
        # Copy and modify config with charge/mult
        CONFIG_SRC="${CONFIGS_DIR}/config_${config}.json"
        CONFIG_DST="${JOB_DIR}/config.json"
        
        # Use python to add charge/mult to config
        python3 << PYEOF
import json
with open("${CONFIG_SRC}", 'r') as f:
    config = json.load(f)
config['charge'] = ${charge}
config['mult'] = ${mult}
with open("${CONFIG_DST}", 'w') as f:
    json.dump(config, f, indent=2)
PYEOF
        
        # Add to job list
        echo "$JOB_NAME" >> "$JOB_LIST"
        JOB_COUNT=$((JOB_COUNT + 1))
    done
    
done < "$REACTION_INFO"

echo
echo "=============================================="
echo "Setup complete!"
echo "=============================================="
echo "Total jobs created: $JOB_COUNT"
echo "Job list: $JOB_LIST"
echo
echo "Jobs created:"
cat "$JOB_LIST"
echo
echo "Next steps:"
echo "1. Edit reaction_info.txt if charge/mult values need adjustment"
echo "2. Run: qsub -t 1-${JOB_COUNT} sge_dft_pipeline.sh"
