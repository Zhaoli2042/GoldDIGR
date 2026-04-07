# ── SNIPPET: round2_prepare_from_partial_results/build_round2_zips_carry_forward_completed_outputs_and_write_skip_txt ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From prepare_round2.sh step 2 (core logic).
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

RESULT_TARBALL="{{RESULT_TARBALL}}"
INPUTS_ABS="{{INPUTS_ABS}}"
ROUND2_DIR="{{ROUND2_DIR:-round2_inputs}}"
WORK_TMP="{{WORK_TMP:-.round2_tmp_$$}}"

mkdir -p "$ROUND2_DIR" "$WORK_TMP"
R2_WORK="$WORK_TMP/r2_build_$$"
mkdir -p "$R2_WORK/result_contents"

tar -xzf "$RESULT_TARBALL" -C "$R2_WORK/result_contents" 2>/dev/null

STATUS_FILE=$(find "$R2_WORK/result_contents" -name "status.json" -type f | head -1)
[ -f "$STATUS_FILE" ] || exit 0

ZIP_NAME=$(grep -o '"zip_file"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATUS_FILE" | sed 's/.*"\([^"]*\)"$/\1/')
[ -n "$ZIP_NAME" ] || exit 0

COMPLETED_MOLS=()
INCOMPLETE_MOLS=()
for mol in "finished_last" "finished_last_opt" "ts_final_geometry" "finished_first" "finished_first_opt" "input"; do
  mol_status=$(grep -o "\"$mol\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$STATUS_FILE" | sed 's/.*"\([^"]*\)"$/\1/')
  if [ "$mol_status" = "complete" ] || [ "$mol_status" = "complete_previous_round" ]; then
    COMPLETED_MOLS+=("$mol")
  elif [ "$mol_status" = "timeout_skipped" ] || [ "$mol_status" = "timeout_killed" ]; then
    INCOMPLETE_MOLS+=("$mol")
  fi
done
[ ${#INCOMPLETE_MOLS[@]} -gt 0 ] || exit 0

ORIGINAL_ZIP=$(find "$INPUTS_ABS" -name "$ZIP_NAME" -type f | head -1)
[ -f "$ORIGINAL_ZIP" ] || exit 0

R2_BUILD="$R2_WORK/build"
mkdir -p "$R2_BUILD"

unzip -q -j "$ORIGINAL_ZIP" -d "$R2_BUILD"

for completed_mol in "${COMPLETED_MOLS[@]}"; do
  for pattern in "${completed_mol}.out" "${completed_mol}.inp" \
                 "${completed_mol}_mayer_mat.txt" "${completed_mol}_wiberg_mat.txt" \
                 "${completed_mol}_fuzzy_mat.txt" "${completed_mol}_mayer_log.out" \
                 "${completed_mol}_wiberg_log.out" "${completed_mol}_fuzzy_log.out"; do
    found_file=$(find "$R2_WORK/result_contents" -name "$pattern" -type f | head -1)
    if [ -n "$found_file" ] && [ -f "$found_file" ]; then
      cp "$found_file" "$R2_BUILD/"
    fi
  done
done

> "$R2_BUILD/skip.txt"
for completed_mol in "${COMPLETED_MOLS[@]}"; do
  echo "$completed_mol" >> "$R2_BUILD/skip.txt"
done

ORIGINAL_RELPATH="${ORIGINAL_ZIP#$INPUTS_ABS/}"
ORIGINAL_RELDIR=$(dirname "$ORIGINAL_RELPATH")
R2_DEST_DIR="$ROUND2_DIR/$ORIGINAL_RELDIR"
mkdir -p "$R2_DEST_DIR"

R2_ZIP="$R2_DEST_DIR/$ZIP_NAME"
(cd "$R2_BUILD" && zip -q "$(cd "{{SCRIPT_DIR:-.}}" && pwd)/$R2_ZIP" *)

echo "Created round-2 zip: $R2_ZIP"
rm -rf "$R2_WORK"
