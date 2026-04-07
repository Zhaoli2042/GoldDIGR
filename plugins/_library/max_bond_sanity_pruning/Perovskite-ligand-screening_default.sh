# ── SNIPPET: max_bond_sanity_pruning/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/adjacency.py
# Invariants:
#   - Only prune when Max_Bonds[element] is not None and sum(adj_row) exceeds it.
#   - Remove bonds in descending distance order (longest first).
# Notes: This block is embedded inside Table_generator; extracted here as the tested logic.
# ────────────────────────────────────────────────────────────

# Perform some simple checks on bonding to catch errors
problem_dict = { i:0 for i in list(Radii.keys()) }
conditions = { "H":1, "C":4, "F":1, "Cl":1, "Br":1, "I":1, "O":2, "N":4, "B":4 }
for count_i,i in enumerate(Adj_mat):

    if Max_Bonds[Elements[count_i]] is not None and sum(i) > Max_Bonds[Elements[count_i]]:
        problem_dict[Elements[count_i]] += 1
        cons = sorted([ (Dist_Mat[count_i,count_j],count_j) if count_j > count_i else (Dist_Mat[count_j,count_i],count_j) for count_j,j in enumerate(i) if j == 1 ])[::-1]
        while sum(Adj_mat[count_i]) > Max_Bonds[Elements[count_i]]:
            sep,idx = cons.pop(0)
            Adj_mat[count_i,idx] = 0
            Adj_mat[idx,count_i] = 0
