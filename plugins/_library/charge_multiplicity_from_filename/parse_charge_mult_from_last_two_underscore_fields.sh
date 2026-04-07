# ── SNIPPET: charge_multiplicity_from_filename/parse_charge_mult_from_last_two_underscore_fields ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Notes: Used by run_orca_wbo.sh.
# ────────────────────────────────────────────────────────────

ZIP_ARGUMENT=$1
ZIP_FILENAME=$(basename "$ZIP_ARGUMENT")
ZIP_BASENAME=$(basename "$ZIP_FILENAME" .zip)

CHARGE=$(echo "$ZIP_BASENAME" | awk -F_ '{print $(NF-1)}')
MULT=$(echo "$ZIP_BASENAME" | awk -F_ '{print $NF}')

echo "Processing $ZIP_FILENAME"
echo "-> Extracted Metadata: Charge=$CHARGE, Multiplicity=$MULT"
