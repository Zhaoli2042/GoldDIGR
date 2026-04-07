# ── SNIPPET: charge_multiplicity_from_filename/parse_charge_mult_from_last_two_underscore_fields_basename ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From run_orca_wbo.sh metadata parsing.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

ZIP_ARGUMENT="{{ZIP_PATH}}"
ZIP_FILENAME=$(basename "$ZIP_ARGUMENT")
ZIP_BASENAME=$(basename "$ZIP_FILENAME" .zip)

CHARGE=$(echo "$ZIP_BASENAME" | awk -F_ '{print $(NF-1)}')
MULT=$(echo "$ZIP_BASENAME" | awk -F_ '{print $NF}')

echo "Charge=$CHARGE"
echo "Multiplicity=$MULT"
