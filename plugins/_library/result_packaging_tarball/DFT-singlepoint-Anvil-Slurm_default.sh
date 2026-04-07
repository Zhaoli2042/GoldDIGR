# ── SNIPPET: result_packaging_tarball/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Use find -print0 and tar --null -T - to safely handle filenames.
#   - Include exactly: *.out, *.xyz, *.inp, *_mat.txt, *_log.out, status.json.
# Notes: Produces results.tar.gz in current directory; external wrapper may rename/move it.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: result_packaging_tarball.sh

echo -e "\nPacking results..."
find . -maxdepth 1 \( -name "*.out" -o -name "*.xyz" -o -name "*.inp" -o -name "*_mat.txt" -o -name "*_log.out" -o -name "status.json" \) -print0 \
  | tar -czf results.tar.gz --null -T -
echo "Done."
