# ── SNIPPET: artifact_exclusion_golddigrignore/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Exclude jobs/ and Test-DFT/ to avoid ingesting large datasets.
#   - Exclude ORCA binary artifacts (*.gbw, *.hess, *.carthess) and large trajectories (*_trj.xyz).
# Notes: Keep patterns as-is.
# ────────────────────────────────────────────────────────────

# plugins/DFT-singlepoint-CRC-SGE/.golddigrignore

# Job output directories (not workflow code)
jobs/

# Job input directories (contains xyz files)
Test-DFT/

# Binary files from ORCA
*.gbw
*.hess
*.carthess

# Large trajectory files
*_trj.xyz
