# ── SNIPPET: charge_multiplicity_from_filename/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Filename convention: <id>_<charge>_<multiplicity>.zip; charge is NF-1 and mult is NF.
# Notes: Assumes no extra underscore tokens after multiplicity.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: charge_multiplicity_from_filename.sh

ZIP_ARGUMENT="{{ZIP_PATH}}"

ZIP_FILENAME=$(basename "$ZIP_ARGUMENT")
ZIP_BASENAME=$(basename "$ZIP_FILENAME" .zip)

CHARGE=$(echo "$ZIP_BASENAME" | awk -F_ '{print $(NF-1)}')
MULT=$(echo "$ZIP_BASENAME" | awk -F_ '{print $NF}')

echo "CHARGE=$CHARGE MULT=$MULT"
