# ── SNIPPET: round2_prepare_from_partial_results/DFT-singlepoint-OSG-Condor_default ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Invariants:
#   - Partial detection is based on extracting status.json and reading \"status\": \"partial\".
#   - Round-2 zip must include skip.txt listing completed molecule names.
#   - Carry forward completed outputs so final results are self-contained.
#   - Only retry timeout_skipped/timeout_killed molecules; do not retry orca_failed/missing.
# Notes: Full tested prepare_round2.sh as provided.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: prepare_round2.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ROUND2_DIR="round2_inputs"
WORK_TMP=".round2_tmp_$$"

SCAN_DIRS=()
[ -d "results" ] && SCAN_DIRS+=("results")

DEST_BASE="/ospool/ap40/data/$USER"
PROJECT_PARENT=$(basename "$(dirname "$SCRIPT_DIR")")
BACKUP_DIR="$DEST_BASE/dft_energy_backups/$PROJECT_PARENT"
[ -d "$BACKUP_DIR" ] && SCAN_DIRS+=("$BACKUP_DIR")

if [ -n "$1" ] && [ -d "$1" ]; then
    SCAN_DIRS=("$1")
fi

mkdir -p "$ROUND2_DIR"
mkdir -p "$WORK_TMP"
trap "rm -rf '$WORK_TMP'" EXIT

INPUTS_ABS=""
[ -d "inputs" ] && INPUTS_ABS="$(cd inputs && pwd)"

PARTIAL_LIST="$WORK_TMP/partial_jobs.txt"
> "$PARTIAL_LIST"

TOTAL_SCANNED=0
PARTIAL_COUNT=0

for SCAN_DIR in "${SCAN_DIRS[@]}"; do
    while IFS= read -r result_tarball; do
        [ -f "$result_tarball" ] || continue
        TOTAL_SCANNED=$((TOTAL_SCANNED + 1))

        EXTRACT_DIR="$WORK_TMP/check_$TOTAL_SCANNED"
        mkdir -p "$EXTRACT_DIR"

        if tar -xzf "$result_tarball" -C "$EXTRACT_DIR" --wildcards '*/status.json' 'status.json' 2>/dev/null || \
           tar -xzf "$result_tarball" -C "$EXTRACT_DIR" status.json 2>/dev/null; then

            STATUS_FILE=$(find "$EXTRACT_DIR" -name "status.json" -type f | head -1)
            if [ -n "$STATUS_FILE" ] && [ -f "$STATUS_FILE" ]; then
                STATUS=$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATUS_FILE" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
                if [ "$STATUS" = "partial" ]; then
                    PARTIAL_COUNT=$((PARTIAL_COUNT + 1))
                    echo "$result_tarball $STATUS_FILE" >> "$PARTIAL_LIST"
                fi
            fi
        fi

        rm -rf "$EXTRACT_DIR"
    done < <(find "$SCAN_DIR" -name "*_results.tar.gz" -type f 2>/dev/null)

    while IFS= read -r backup_archive; do
        [ -f "$backup_archive" ] || continue
        INNER_RESULTS=$(tar -tzf "$backup_archive" 2>/dev/null | grep "_results\.tar\.gz$" || true)
        [ -z "$INNER_RESULTS" ] && continue

        BACKUP_EXTRACT="$WORK_TMP/backup_extract_$$"
        mkdir -p "$BACKUP_EXTRACT"
        tar -xzf "$backup_archive" -C "$BACKUP_EXTRACT" 2>/dev/null || continue

        while IFS= read -r inner_result; do
            [ -z "$inner_result" ] && continue
            INNER_PATH="$BACKUP_EXTRACT/$inner_result"
            [ -f "$INNER_PATH" ] || continue

            TOTAL_SCANNED=$((TOTAL_SCANNED + 1))

            EXTRACT_DIR="$WORK_TMP/check_inner_$TOTAL_SCANNED"
            mkdir -p "$EXTRACT_DIR"

            if tar -xzf "$INNER_PATH" -C "$EXTRACT_DIR" --wildcards '*/status.json' 'status.json' 2>/dev/null || \
               tar -xzf "$INNER_PATH" -C "$EXTRACT_DIR" status.json 2>/dev/null; then

                STATUS_FILE=$(find "$EXTRACT_DIR" -name "status.json" -type f | head -1)
                if [ -n "$STATUS_FILE" ] && [ -f "$STATUS_FILE" ]; then
                    STATUS=$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATUS_FILE" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
                    if [ "$STATUS" = "partial" ]; then
                        PARTIAL_COUNT=$((PARTIAL_COUNT + 1))
                        echo "$INNER_PATH $STATUS_FILE" >> "$PARTIAL_LIST"
                    fi
                fi
            fi

            rm -rf "$EXTRACT_DIR"
        done <<< "$INNER_RESULTS"

        rm -rf "$BACKUP_EXTRACT"
    done < <(find "$SCAN_DIR" -name "backup_*.tar.gz" -type f 2>/dev/null)
done

[ "$PARTIAL_COUNT" -eq 0 ] && exit 0

ROUND2_COUNT=0
SKIPPED_NO_ORIGINAL=0
> "$WORK_TMP/file_list_round2.txt"

while IFS=' ' read -r result_tarball status_file_ignored; do
    [ -z "$result_tarball" ] && continue
    [ -f "$result_tarball" ] || continue

    R2_WORK="$WORK_TMP/r2_build_$ROUND2_COUNT"
    mkdir -p "$R2_WORK/result_contents"
    tar -xzf "$result_tarball" -C "$R2_WORK/result_contents" 2>/dev/null || continue

    STATUS_FILE=$(find "$R2_WORK/result_contents" -name "status.json" -type f | head -1)
    [ -f "$STATUS_FILE" ] || { rm -rf "$R2_WORK"; continue; }

    ZIP_NAME=$(grep -o '"zip_file"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATUS_FILE" | sed 's/.*"\([^"]*\)"$/\1/')
    [ -z "$ZIP_NAME" ] && { rm -rf "$R2_WORK"; continue; }

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

    if [ ${#INCOMPLETE_MOLS[@]} -eq 0 ]; then
        rm -rf "$R2_WORK"
        continue
    fi

    ORIGINAL_ZIP=""
    if [ -n "$INPUTS_ABS" ]; then
        ORIGINAL_ZIP=$(find "$INPUTS_ABS" -name "$ZIP_NAME" -type f | head -1)
    fi

    if [ -z "$ORIGINAL_ZIP" ] || [ ! -f "$ORIGINAL_ZIP" ]; then
        SKIPPED_NO_ORIGINAL=$((SKIPPED_NO_ORIGINAL + 1))
        rm -rf "$R2_WORK"
        continue
    fi

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
    (cd "$R2_BUILD" && zip -q "$SCRIPT_DIR/$R2_ZIP" *)

    ROUND2_COUNT=$((ROUND2_COUNT + 1))

    R2_ZIP_ABS="$(cd "$SCRIPT_DIR" && pwd)/$R2_ZIP"
    R2_RELPATH="${R2_ZIP#$ROUND2_DIR/}"
    R2_RELPATH_NO_EXT="${R2_RELPATH%.zip}"
    echo "$R2_ZIP_ABS, $R2_RELPATH_NO_EXT" >> "$WORK_TMP/file_list_round2.txt"

    rm -rf "$R2_WORK"
done < "$PARTIAL_LIST"

[ "$ROUND2_COUNT" -eq 0 ] && exit 0

cp "$WORK_TMP/file_list_round2.txt" "$SCRIPT_DIR/file_list_round2.txt"

if [ -d "results" ]; then
    (cd "$ROUND2_DIR" && find . -type d -exec mkdir -p "$SCRIPT_DIR/results/{}" \;)
fi
