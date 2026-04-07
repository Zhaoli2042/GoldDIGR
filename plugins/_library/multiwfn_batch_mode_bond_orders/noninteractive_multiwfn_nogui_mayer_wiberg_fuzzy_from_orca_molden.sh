# ── SNIPPET: multiwfn_batch_mode_bond_orders/noninteractive_multiwfn_nogui_mayer_wiberg_fuzzy_from_orca_molden ─
# Scheduler:   any
# Tool:        multiwfn
# Tested:      golddigr
# Notes: From run_orca_wbo.sh.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

MOL="{{MOL}}"

# Convert to Molden
/opt/orca/orca_2mkl "${MOL}" -molden > /dev/null 2>&1

if [ -f "${MOL}.molden.input" ]; then
  # Mayer
  cat > run_mayer.txt <<EOF
9
1
y
0
q
EOF
  /opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_mayer.txt > "${MOL}_mayer_log.out" 2>/dev/null
  [ -f bndmat.txt ] && mv bndmat.txt "${MOL}_mayer_mat.txt"

  # Wiberg (Lowdin)
  cat > run_wiberg.txt <<EOF
9
3
y
0
q
EOF
  /opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_wiberg.txt > "${MOL}_wiberg_log.out" 2>/dev/null
  [ -f bndmat.txt ] && mv bndmat.txt "${MOL}_wiberg_mat.txt"

  # Fuzzy
  cat > run_fuzzy.txt <<EOF
9
7
y
0
q
EOF
  /opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_fuzzy.txt > "${MOL}_fuzzy_log.out" 2>/dev/null
  [ -f bndmat.txt ] && mv bndmat.txt "${MOL}_fuzzy_mat.txt"

  rm -f run_mayer.txt run_wiberg.txt run_fuzzy.txt
else
  echo "Warning: Molden conversion failed"
fi
