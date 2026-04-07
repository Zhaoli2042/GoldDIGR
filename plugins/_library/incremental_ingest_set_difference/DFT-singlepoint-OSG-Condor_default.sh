# ── SNIPPET: incremental_ingest_set_difference/DFT-singlepoint-OSG-Condor_default ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Invariants:
#   - file_list.txt column 1 must be absolute zip paths; comm requires both lists sorted.
#   - Never re-add zips already tracked; safe to run multiple times.
#   - Mirrors directory structure from inputs/ into results/ after ingest.
# Notes: This is the full tested add_data.sh (includes chunk continuation + selective monitor restart).
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: add_data.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

JOBS_PER_CHUNK={{JOBS_PER_CHUNK}}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║              DFT Energy — Add New Input Data                ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ $# -gt 0 ]; then
    INPUT_TARBALLS="$@"
else
    INPUT_TARBALLS=$(ls *.tar.gz 2>/dev/null | grep -v 'results_package' | grep -v 'backup_' || true)
fi

if [ -z "$INPUT_TARBALLS" ]; then
    echo -e "${RED}Error: No *.tar.gz files found.${NC}"
    exit 1
fi

if [ ! -f "file_list.txt" ]; then
    echo -e "${RED}Error: file_list.txt not found. Run start.sh first to initialize the workflow.${NC}"
    exit 1
fi

if [ ! -d "inputs" ] || [ ! -d "results" ]; then
    echo -e "${RED}Error: inputs/ or results/ directory missing. Run start.sh first.${NC}"
    exit 1
fi

echo -e "${YELLOW}[1/5]${NC} Extracting new input archives..."
for TARBALL in $INPUT_TARBALLS; do
    if [ ! -f "$TARBALL" ]; then
        echo -e "  ${YELLOW}Warning:${NC} $TARBALL not found, skipping"
        continue
    fi
    echo "  Extracting: $(basename "$TARBALL")"
    tar -xzf "$TARBALL" -C inputs/
done
echo -e "  ${GREEN}✓ Done${NC}"
echo ""

echo -e "${YELLOW}[2/5]${NC} Scanning for new .zip files..."

INPUTS_ABS="$(cd inputs && pwd)"

ALL_ZIPS_FILE=".all_zips_$$.txt"
find "$INPUTS_ABS" -name "*.zip" -type f | sort > "$ALL_ZIPS_FILE"

TRACKED_ZIPS_FILE=".tracked_zips_$$.txt"
awk -F', ' '{print $1}' file_list.txt | sort > "$TRACKED_ZIPS_FILE"

NEW_ZIPS_FILE=".new_zips_$$.txt"
comm -23 "$ALL_ZIPS_FILE" "$TRACKED_ZIPS_FILE" > "$NEW_ZIPS_FILE"

rm -f "$ALL_ZIPS_FILE" "$TRACKED_ZIPS_FILE"

NEW_COUNT=$(wc -l < "$NEW_ZIPS_FILE")
if [ "$NEW_COUNT" -eq 0 ]; then
    echo -e "  ${YELLOW}No new .zip files found.${NC}"
    rm -f "$NEW_ZIPS_FILE"
    exit 0
fi

NEW_LIST_FILE=".new_entries_$$.txt"
while IFS= read -r zipfile; do
    relpath="${zipfile#$INPUTS_ABS/}"
    relpath_no_ext="${relpath%.zip}"
    echo "$zipfile, $relpath_no_ext"
done < "$NEW_ZIPS_FILE" > "$NEW_LIST_FILE"
rm -f "$NEW_ZIPS_FILE"

echo -e "${YELLOW}[3/5]${NC} Updating file_list.txt and mirroring directories..."
cat "$NEW_LIST_FILE" >> file_list.txt
(cd inputs && find . -type d -exec mkdir -p "../results/{}" \;)
echo -e "  ${GREEN}✓ Done${NC}"
echo ""

echo -e "${YELLOW}[4/5]${NC} Creating job chunks for new entries..."

MAX_NUM=0
ALL_JOB_FILES=$(ls job_*.txt submitted_batches/job_*.txt 2>/dev/null || true)
for f in $ALL_JOB_FILES; do
    [ -f "$f" ] || continue
    num=$(basename "$f" | sed -n 's/^job_\([0-9]\+\)\.txt$/\1/p')
    if [ -n "$num" ] && [ "$num" -gt "$MAX_NUM" ]; then
        MAX_NUM=$num
    fi
done

NEXT_NUM=$((MAX_NUM + 1))

CHUNK_NUM=$((NEXT_NUM - 1))
LINE_NUM=0
CHUNKS_CREATED=0

while IFS= read -r line || [ -n "$line" ]; do
    if [ $((LINE_NUM % JOBS_PER_CHUNK)) -eq 0 ]; then
        CHUNK_NUM=$((CHUNK_NUM + 1))
        CHUNK_FILE="job_${CHUNK_NUM}.txt"
        > "$CHUNK_FILE"
        CHUNKS_CREATED=$((CHUNKS_CREATED + 1))
    fi
    echo "$line" >> "$CHUNK_FILE"
    LINE_NUM=$((LINE_NUM + 1))
done < "$NEW_LIST_FILE"

rm -f "$NEW_LIST_FILE"

echo -e "${GREEN}✓ Done${NC}"
echo ""

echo -e "${YELLOW}[5/5]${NC} Restarting submit monitor..."

if tmux has-session -t submit 2>/dev/null; then
    tmux kill-session -t submit 2>/dev/null || true
    sleep 2
fi

tmux new-session -d -s submit "cd $SCRIPT_DIR && ./monitor_submit.sh"
echo -e "  Started: ${GREEN}submit${NC}"
