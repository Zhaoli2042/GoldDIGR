# ── SNIPPET: round2_skiplist_loader/load_skip_txt_and_mark_complete_previous_round ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From run_orca_wbo.sh.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

SKIP_FILE="{{SKIP_FILE:-skip.txt}}"
declare -A SKIP_MOLECULES

if [ -f "$SKIP_FILE" ]; then
  while IFS= read -r mol_name || [ -n "$mol_name" ]; do
    mol_name=$(echo "$mol_name" | xargs)
    [ -z "$mol_name" ] && continue
    SKIP_MOLECULES["$mol_name"]=1
  done < "$SKIP_FILE"
fi
