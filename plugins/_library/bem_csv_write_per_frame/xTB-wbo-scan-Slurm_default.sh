# ── SNIPPET: bem_csv_write_per_frame/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        xtb | any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Off-diagonal bond electrons = 2*WBO; bond orders = WBO.
#   - Diagonal bond-electrons uses: nominal_valence(element) - sum_incident_WBO (conservation-consistent).
#   - All missing off-diagonals must be explicit 0.0 to stabilize downstream diffs.
#   - Frame index is zero-padded to 5 digits: frame_00001_*.
# Notes: `charges` is accepted but not used in this implementation (kept as-tested).
# ────────────────────────────────────────────────────────────

from pathlib import Path

# Nominal valence electrons (H–Rn), keys capitalized to match XYZ symbols
NOMINAL_VALENCE = {
    "H": 1, "He": 2,
    "Li": 1, "Be": 2, "B": 3, "C": 4, "N": 5, "O": 6, "F": 7, "Ne": 8,
    "Na": 1, "Mg": 2, "Al": 3, "Si": 4, "P": 5, "S": 6, "Cl": 7, "Ar": 8,
    "K": 1, "Ca": 2, "Sc": 3, "Ti": 4, "V": 5, "Cr": 6, "Mn": 7, "Fe": 8, "Co": 9, "Ni": 10, "Cu": 11, "Zn": 12,
    "Ga": 3, "Ge": 4, "As": 5, "Se": 6, "Br": 7, "Kr": 8,
    "Rb": 1, "Sr": 2, "Y": 3, "Zr": 4, "Nb": 5, "Mo": 6, "Tc": 7, "Ru": 8, "Rh": 9, "Pd": 10, "Ag": 11, "Cd": 12,
    "In": 3, "Sn": 4, "Sb": 5, "Te": 6, "I": 7, "Xe": 8,
    "Cs": 1, "Ba": 2, "La": 3, "Hf": 4, "Ta": 5, "W": 6, "Re": 7, "Os": 8, "Ir": 9, "Pt": 10, "Au": 11, "Hg": 12,
    "Tl": 3, "Pb": 4, "Bi": 5, "Po": 6, "At": 7, "Rn": 8,
    "Ce": 3,"Pr": 3,"Nd": 3,"Pm": 3,"Sm": 3,"Eu": 3,"Gd": 3,
    "Tb": 3,"Dy": 3,"Ho": 3,"Er": 3,"Tm": 3,"Yb": 3,"Lu": 3,
    "Ac": 3,"Th": 3,"Pa": 3,"U": 3, "Np": 3,"Pu": 3,"Am": 3,"Cm": 3,
    "Bk": 3,"Cf": 3,"Es": 3,"Fm": 3,"Md": 3,"No": 3,"Lr": 3
}

def write_bem_csvs(symbols, charges, wbo_pairs, out_dir, frame_idx):
    """
    Write two CSVs per frame:
      frame_#####_bond_electrons.csv  (off-diag = 2*WBO; diag ~ valence - Mulliken charge if available)
      frame_#####_bond_orders.csv     (off-diag = WBO;  diag blank)
    Header row/col are atom labels like C0, H1, ...
    """
    from csv import writer

    n = len(symbols)
    # Sum of WBOs incident to each atom (for conservation-consistent diagonal)
    sum_wbo = [0.0] * n
    for (a, b), w in wbo_pairs.items():
        w = float(w)
        sum_wbo[a] += w
        sum_wbo[b] += w

    labels = [f"{symbols[i]}{i}" for i in range(n)]
    # Build dense matrices
    M_e = [[""] * (n + 1) for _ in range(n + 1)]
    M_o = [[""] * (n + 1) for _ in range(n + 1)]

    # headers
    M_e[0][0] = ""
    M_o[0][0] = ""
    for j in range(n):
        M_e[0][j+1] = labels[j]
        M_o[0][j+1] = labels[j]

    # Initialize all off-diagonals to 0 (so missing WBO → solid 0)
    for i in range(n):
        for j in range(n):
            if i != j:
                M_e[i+1][j+1] = 0.0
                # If you ALSO want zeros in bond_orders.csv off-diagonals, keep the next line:
                M_o[i+1][j+1] = 0.0

    # fill rows
    for i in range(n):
        M_e[i+1][0] = labels[i]
        M_o[i+1][0] = labels[i]
        # diagonals (valence-only): d_i = V0 - sum_j WBO_ij
        sym = symbols[i]
        V0  = NOMINAL_VALENCE.get(sym)
        if V0 is not None:
            di = float(V0) - float(sum_wbo[i])
            # clean tiny negatives due to numerical noise
            if abs(di) < 1e-8:
                di = 0.0
            elif di < 0.0 and di > -1e-3:
                di = 0.0
            M_e[i+1][i+1] = di
        else:
            M_e[i+1][i+1] = ""
        # order-BEM keeps blank diagonal
        M_o[i+1][i+1] = ""
    # off-diagonals from WBO
    for (a,b), w in wbo_pairs.items():
        # electrons matrix gets 2*WBO, order matrix gets WBO
        val_e = 2.0 * float(w)
        val_o = float(w)
        ia, ib = a+1, b+1
        M_e[ia][ib] = val_e
        M_e[ib][ia] = val_e
        M_o[ia][ib] = val_o
        M_o[ib][ia] = val_o

    # write files (use 5-digit frame index to match your YARP naming)
    p_e = Path(out_dir) / f"frame_{frame_idx:05d}_bond_electrons.csv"
    p_o = Path(out_dir) / f"frame_{frame_idx:05d}_bond_orders.csv"
    with open(p_e, "w", newline="") as f:
        w = writer(f)
        for row in M_e: w.writerow(row)
    with open(p_o, "w", newline="") as f:
        w = writer(f)
        for row in M_o: w.writerow(row)
