# ── SNIPPET: multiwfn_batch_mode_bond_orders/multiwfn_nogui_batch_rename_bndmat_outputs ─
# Scheduler:   any
# Tool:        multiwfn
# Tested:      dft_energy_orca_multiwfn
# Notes: Suppresses stdout to /dev/null in original.
# ────────────────────────────────────────────────────────────

# 1. Mayer Bond Order
cat > run_mayer.txt <<EOF
9
1
y
0
q
EOF
/opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_mayer.txt > "${MOL}_mayer_log.out" 2>/dev/null
if [ -f bndmat.txt ]; then
    mv bndmat.txt "${MOL}_mayer_mat.txt"
fi

# 2. Wiberg Bond Order (Lowdin)
cat > run_wiberg.txt <<EOF
9
3
y
0
q
EOF
/opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_wiberg.txt > "${MOL}_wiberg_log.out" 2>/dev/null
if [ -f bndmat.txt ]; then
    mv bndmat.txt "${MOL}_wiberg_mat.txt"
fi

# 3. Fuzzy Bond Order
cat > run_fuzzy.txt <<EOF
9
7
y
0
q
EOF
/opt/Multiwfn_bin/Multiwfn_noGUI "${MOL}.molden.input" < run_fuzzy.txt > "${MOL}_fuzzy_log.out" 2>/dev/null
if [ -f bndmat.txt ]; then
    mv bndmat.txt "${MOL}_fuzzy_mat.txt"
fi

rm -f run_mayer.txt run_wiberg.txt run_fuzzy.txt
