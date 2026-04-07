# ── SNIPPET: ops_status_dashboard/DFT-singlepoint-OSG-Condor_default ─
# Scheduler:   htcondor
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Invariants:
#   - Uses condor_q if available; otherwise degrades gracefully.
#   - Chunk progress is inferred from job_*.txt vs submitted_batches/job_*.txt.
#   - Held job reasons are summarized by HoldReason frequency.
# Notes: Contains site-specific backup path logic; parameterize if reusing.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: status.sh

USER_ID="${USER}"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                 DFT Energy — Workflow Status                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo "📊 Queue Status"
echo "───────────────────────────────────────"
if command -v condor_q &> /dev/null; then
    condor_q "$USER_ID" 2>/dev/null | tail -3
else
    echo "  (condor_q not available)"
fi
echo ""

echo "📁 Submission Progress"
echo "───────────────────────────────────────"
PENDING=$(ls -1 job_*.txt 2>/dev/null | wc -l)
SUBMITTED=$(ls -1 submitted_batches/job_*.txt 2>/dev/null | wc -l)
echo "  Chunks pending:    $PENDING"
echo "  Chunks submitted:  $SUBMITTED"
if [ -f "file_list.txt" ]; then
    TOTAL_JOBS=$(wc -l < file_list.txt)
    echo "  Total jobs:        $TOTAL_JOBS"
fi
echo ""

echo "⚠️  Held Jobs"
echo "───────────────────────────────────────"
if command -v condor_q &> /dev/null; then
    HELD_COUNT=$(condor_q "$USER_ID" -constraint 'JobStatus == 5' -format "%d\n" ClusterId 2>/dev/null | wc -l)
    if [ "$HELD_COUNT" -gt 0 ]; then
        echo "  Total held: $HELD_COUNT"
        echo ""
        echo "  Top hold reasons:"
        condor_q "$USER_ID" -constraint 'JobStatus == 5' -format "%s\n" HoldReason 2>/dev/null | \
            sort | uniq -c | sort -rn | head -5 | \
            while read -r count reason; do
                reason_short=$(echo "$reason" | cut -c1-50)
                printf "    %4d — %s\n" "$count" "$reason_short"
            done
    else
        echo "  None! 🎉"
    fi
else
    echo "  (condor_q not available)"
fi
echo ""

if [ -f "held_jobs_maxed.log" ] && [ -s "held_jobs_maxed.log" ]; then
    MAXED_COUNT=$(wc -l < held_jobs_maxed.log)
    echo "🛑 Maxed-Out Jobs (need manual review)"
    echo "───────────────────────────────────────"
    echo "  Total: $MAXED_COUNT"
    echo "  Log: held_jobs_maxed.log"
    echo ""
fi

echo "📦 Results"
echo "───────────────────────────────────────"
if [ -d "results" ]; then
    RESULT_COUNT=$(find results -name "*_results.tar.gz" -type f 2>/dev/null | wc -l)
    echo "  Local result files: $RESULT_COUNT"
else
    echo "  (no results/ directory yet)"
fi

DEST_BASE="/ospool/ap40/data/$USER"
PROJECT_PARENT=$(basename "$(dirname "$(pwd)")")
BACKUP_DIR="$DEST_BASE/dft_energy_backups/$PROJECT_PARENT"
if [ -d "$BACKUP_DIR" ]; then
    BACKUP_COUNT=$(ls "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l)
    BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
    echo "  Backups:            $BACKUP_COUNT archives ($BACKUP_SIZE)"
fi
echo ""

echo "🔄 Background Processes"
echo "───────────────────────────────────────"
if command -v tmux &> /dev/null; then
    SESSIONS=$(tmux list-sessions 2>/dev/null | grep -E "submit|health|backup" || echo "")
    if [ -n "$SESSIONS" ]; then
        echo "$SESSIONS" | while read -r line; do
            echo "  $line"
        done
    else
        echo "  No monitor sessions running"
    fi
else
    echo "  (tmux not available)"
fi
echo ""

if [ -f "resource_tracking.dat" ] && [ -s "resource_tracking.dat" ]; then
    TRACKED=$(wc -l < resource_tracking.dat)
    echo "📈 Resource Escalation"
    echo "───────────────────────────────────────"
    echo "  Jobs with upgrades: $TRACKED"
    echo ""
fi
