# ── SNIPPET: task_wrapper_orca_multiwfn_per_zip/per_zip_wrapper_unzip_run_orca_2mkl_multiwfn_clean_pack_with_status ─
# Scheduler:   htcondor
# Tool:        orca | multiwfn
# Tested:      dft_energy_orca_multiwfn
# Notes: This is the full tested run_orca_wbo.sh as provided (including known issue: unzip uses basename).
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: run_orca_wbo.sh

ZIP_ARGUMENT=$1

if [ -z "$ZIP_ARGUMENT" ]; then
    echo "Error: No zip file provided."
    exit 1
fi

ZIP_FILENAME=$(basename "$ZIP_ARGUMENT")
ZIP_BASENAME=$(basename "$ZIP_FILENAME" .zip)

CHARGE=$(echo "$ZIP_BASENAME" | awk -F_ '{print $(NF-1)}')
MULT=$(echo "$ZIP_BASENAME" | awk -F_ '{print $NF}')

WALL_SECONDS=${WALL_SECONDS:-70200}
BUFFER_SECONDS=${BUFFER_SECONDS:-7200}
WATCHDOG_BUFFER=1800
START_TIME=$(date +%s)

time_remaining() {
    local now=$(date +%s)
    local elapsed=$((now - START_TIME))
    echo $((WALL_SECONDS - elapsed))
}

have_time() {
    local remaining=$(time_remaining)
    if [ "$remaining" -gt "$BUFFER_SECONDS" ]; then
        return 0
    else
        return 1
    fi
}

export PATH="/opt/orca:${PATH}"
export LD_LIBRARY_PATH="/opt/orca:${LD_LIBRARY_PATH}"
export OMPI_MCA_rmaps_base_oversubscribe=1
export OMPI_MCA_hwloc_base_binding_policy=none

WATCHDOG_DELAY=$((WALL_SECONDS - WATCHDOG_BUFFER))
WATCHDOG_PID=""

start_watchdog() {
    (
        sleep "$WATCHDOG_DELAY"
        pkill -f "/opt/orca/orca" 2>/dev/null || true
        pkill -f "orca_" 2>/dev/null || true
        sleep 5
        pkill -9 -f "/opt/orca/orca" 2>/dev/null || true
        pkill -9 -f "orca_" 2>/dev/null || true
    ) &
    WATCHDOG_PID=$!
}

stop_watchdog() {
    if [ -n "$WATCHDOG_PID" ]; then
        kill "$WATCHDOG_PID" 2>/dev/null || true
        wait "$WATCHDOG_PID" 2>/dev/null || true
        WATCHDOG_PID=""
    fi
}

trap 'stop_watchdog' EXIT
start_watchdog

unzip -q -j "$ZIP_FILENAME"

declare -A SKIP_MOLECULES
if [ -f "skip.txt" ]; then
    while IFS= read -r mol_name || [ -n "$mol_name" ]; do
        mol_name=$(echo "$mol_name" | xargs)
        [ -z "$mol_name" ] && continue
        SKIP_MOLECULES["$mol_name"]=1
    done < skip.txt
fi

MOLECULES=("finished_last" "finished_last_opt" "ts_final_geometry" "finished_first" "finished_first_opt" "input")

TOTAL_MOLS=${#MOLECULES[@]}
MISSING_COUNT=0
PROCESSED_COUNT=0
SKIPPED_COUNT=0
TIMEOUT_COUNT=0
TIMED_OUT=0

declare -A MOL_STATUS

for MOL in "${MOLECULES[@]}"; do
    XYZ_FILE="${MOL}.xyz"

    if [ -n "${SKIP_MOLECULES[$MOL]+x}" ]; then
        MOL_STATUS["$MOL"]="complete_previous_round"
        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
        continue
    fi

    if [ "$TIMED_OUT" -eq 1 ]; then
        MOL_STATUS["$MOL"]="timeout_skipped"
        TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1))
        continue
    fi

    if ! have_time; then
        MOL_STATUS["$MOL"]="timeout_skipped"
        TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1))
        TIMED_OUT=1
        continue
    fi

    if [ -f "$XYZ_FILE" ]; then
        PROCESSED_COUNT=$((PROCESSED_COUNT + 1))

        cat > "${MOL}.inp" <<EOF
! wB97X-V def2-TZVP def2/J defgrid3 RIJCOSX CHELPG Loewdin Mayer
%scf
  MaxIter 500
end
%pal
  nproc 4
end
%maxcore 2500
%base "${MOL}"
*xyzfile ${CHARGE} ${MULT} ${XYZ_FILE}
EOF

        /opt/orca/orca "${MOL}.inp" > "${MOL}.out"
        ORCA_EXIT=$?

        if [ $ORCA_EXIT -ne 0 ]; then
            REMAINING=$(time_remaining)
            if [ "$REMAINING" -lt "$WATCHDOG_BUFFER" ]; then
                MOL_STATUS["$MOL"]="timeout_killed"
                TIMEOUT_COUNT=$((TIMEOUT_COUNT + 1))
                TIMED_OUT=1
                rm -f "${MOL}.gbw" "${MOL}.out" "${MOL}.inp"
                rm -f *.gbw *.vpot *.dens *.tmp *.cis *.tx *.opt
                continue
            else
                MOL_STATUS["$MOL"]="orca_failed"
                rm -f *.gbw *.vpot *.dens *.tmp *.cis *.tx *.opt
                continue
            fi
        fi

        if [ -f "${MOL}.gbw" ]; then
            /opt/orca/orca_2mkl "${MOL}" -molden > /dev/null 2>&1

            if [ -f "${MOL}.molden.input" ]; then
                cat > run_mayer.txt <<EOF
9
1
y
0
q
EOF
                /opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_mayer.txt > "${MOL}_mayer_log.out" 2>/dev/null
                if [ -f bndmat.txt ]; then mv bndmat.txt "${MOL}_mayer_mat.txt"; fi

                cat > run_wiberg.txt <<EOF
9
3
y
0
q
EOF
                /opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_wiberg.txt > "${MOL}_wiberg_log.out" 2>/dev/null
                if [ -f bndmat.txt ]; then mv bndmat.txt "${MOL}_wiberg_mat.txt"; fi

                cat > run_fuzzy.txt <<EOF
9
7
y
0
q
EOF
                /opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_fuzzy.txt > "${MOL}_fuzzy_log.out" 2>/dev/null
                if [ -f bndmat.txt ]; then mv bndmat.txt "${MOL}_fuzzy_mat.txt"; fi

                rm -f run_mayer.txt run_wiberg.txt run_fuzzy.txt
                MOL_STATUS["$MOL"]="complete"
            else
                MOL_STATUS["$MOL"]="molden_failed"
            fi
        else
            MOL_STATUS["$MOL"]="orca_no_gbw"
        fi

        rm -f *.gbw *.vpot *.dens *.tmp *.cis *.tx *.opt *.molden.input
    else
        MOL_STATUS["$MOL"]="missing"
        MISSING_COUNT=$((MISSING_COUNT + 1))
    fi
done

stop_watchdog

END_TIME=$(date +%s)
TOTAL_ELAPSED=$((END_TIME - START_TIME))

OVERALL_STATUS="complete"
if [ "$TIMEOUT_COUNT" -gt 0 ]; then
    OVERALL_STATUS="partial"
fi

COMPLETE_COUNT=0
for MOL in "${MOLECULES[@]}"; do
    s="${MOL_STATUS[$MOL]}"
    if [ "$s" = "complete" ] || [ "$s" = "complete_previous_round" ]; then
        COMPLETE_COUNT=$((COMPLETE_COUNT + 1))
    fi
done

if [ "$COMPLETE_COUNT" -eq 0 ] && [ "$PROCESSED_COUNT" -eq 0 ]; then
    OVERALL_STATUS="all_molecules_missing"
fi

cat > status.json <<STATUSEOF
{
  "zip_file": "$ZIP_FILENAME",
  "charge": "$CHARGE",
  "multiplicity": "$MULT",
  "status": "$OVERALL_STATUS",
  "wall_limit_seconds": $WALL_SECONDS,
  "elapsed_seconds": $TOTAL_ELAPSED,
  "total_molecules": $TOTAL_MOLS,
  "completed": $COMPLETE_COUNT,
  "timeout_skipped": $TIMEOUT_COUNT,
  "missing": $MISSING_COUNT,
  "molecules": {
STATUSEOF

FIRST=1
for MOL in "${MOLECULES[@]}"; do
    if [ $FIRST -eq 1 ]; then
        FIRST=0
    else
        echo "," >> status.json
    fi
    echo -n "    \"$MOL\": \"${MOL_STATUS[$MOL]:-unknown}\"" >> status.json
done

cat >> status.json <<STATUSEOF

  }
}
STATUSEOF

if [ "$OVERALL_STATUS" = "all_molecules_missing" ] && [ "$PROCESSED_COUNT" -eq 0 ]; then
    tar -czf results.tar.gz status.json
else
    find . -maxdepth 1 \( \
        -name "*.out" -o -name "*.xyz" -o -name "*.inp" -o \
        -name "*_mat.txt" -o -name "*_log.out" -o \
        -name "status.json" \
    \) -print0 | tar -czf results.tar.gz --null -T -
fi
