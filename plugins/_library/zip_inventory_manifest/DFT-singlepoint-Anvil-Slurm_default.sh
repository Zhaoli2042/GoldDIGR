# ── SNIPPET: zip_inventory_manifest/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Manifest line format must remain: '<abs_zip_path>, <relative_path>' (comma+space) before downstream parsing.
#   - Strip '.zip' suffix from both fields using sed 's/\\.zip$//'.
# Notes: Downstream manager.sh trims a trailing comma from ZIP_PATH; keep the comma in column 1.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: zip_inventory_manifest.sh

SOURCE_DIR="{{SOURCE_DIR}}"
MANIFEST_OUT="{{MANIFEST_OUT}}"   # e.g., /path/to/file_list.txt

find "$SOURCE_DIR" -name "*.zip" -printf "%p, %P\n" | sed 's/\.zip$//' > "$MANIFEST_OUT"
