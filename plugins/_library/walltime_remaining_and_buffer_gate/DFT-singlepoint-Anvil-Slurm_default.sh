# ── SNIPPET: walltime_remaining_and_buffer_gate/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - have_time returns success only if remaining > BUFFER_SECONDS.
# Notes: Must set START_TIME at beginning of job.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: walltime_remaining_and_buffer_gate.sh

WALL_SECONDS=${WALL_SECONDS:-86400}
BUFFER_SECONDS=${BUFFER_SECONDS:-3600}
START_TIME=$(date +%s)

time_remaining() {
  local now=$(date +%s)
  local elapsed=$((now - START_TIME))
  echo $((WALL_SECONDS - elapsed))
}

have_time() {
  local remaining
  remaining=$(time_remaining)
  if [ "$remaining" -gt "$BUFFER_SECONDS" ]; then return 0; else return 1; fi
}
