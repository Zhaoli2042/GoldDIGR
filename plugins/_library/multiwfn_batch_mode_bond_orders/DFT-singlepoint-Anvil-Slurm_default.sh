# ── SNIPPET: multiwfn_batch_mode_bond_orders/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        multiwfn
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Requires ${MOL}.gbw to exist; generates molden via orca_2mkl.
#   - Menu scripts must remain exactly: 9/1, 9/3, 9/7 sequences with 'y', '0', 'q'.
#   - Multiwfn writes bndmat.txt; must be renamed after each run.
# Notes: Assumes Multiwfn_noGUI is on PATH and orca_2mkl at /opt/orca/orca_2mkl.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: multiwfn_batch_mode_bond_orders.sh

MOL="{{MOL}}"

if [ -f "${MOL}.gbw" ]; then
  /opt/orca/orca_2mkl "${MOL}" -molden > /dev/null 2>&1
  if [ -f "${MOL}.molden.input" ]; then
    printf "9\n1\ny\n0\nq\n" | Multiwfn_noGUI "${MOL}.molden.input" > "${MOL}_mayer_log.out" 2>/dev/null
    [ -f bndmat.txt ] && mv bndmat.txt "${MOL}_mayer_mat.txt"

    printf "9\n3\ny\n0\nq\n" | Multiwfn_noGUI "${MOL}.molden.input" > "${MOL}_wiberg_log.out" 2>/dev/null
    [ -f bndmat.txt ] && mv bndmat.txt "${MOL}_wiberg_mat.txt"

    printf "9\n7\ny\n0\nq\n" | Multiwfn_noGUI "${MOL}.molden.input" > "${MOL}_fuzzy_log.out" 2>/dev/null
    [ -f bndmat.txt ] && mv bndmat.txt "${MOL}_fuzzy_mat.txt"

    exit 0
  else
    exit 2
  fi
else
  exit 3
fi
