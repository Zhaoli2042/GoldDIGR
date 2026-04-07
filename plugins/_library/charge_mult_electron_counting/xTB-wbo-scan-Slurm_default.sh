# ── SNIPPET: charge_mult_electron_counting/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Element symbols are normalized to 'Fe' style before lookup.
#   - Total electrons = sum(Z) - charge.
#   - Base UHF is 0 for even-electron systems else 1.
# Notes: Extend EL_TO_Z if new elements appear.
# ────────────────────────────────────────────────────────────

# Element → Atomic Number (H–Rn), symbols capitalized
EL_TO_Z = {
    "H": 1,  "He": 2,
    "Li": 3, "Be": 4,  "B": 5,  "C": 6,  "N": 7,  "O": 8,  "F": 9,  "Ne": 10,
    "Na": 11,"Mg": 12, "Al": 13,"Si": 14,"P": 15, "S": 16,"Cl": 17,"Ar": 18,
    "K": 19, "Ca": 20, "Sc": 21,"Ti": 22,"V": 23, "Cr": 24,"Mn": 25,"Fe": 26,"Co": 27,"Ni": 28,
    "Cu": 29,"Zn": 30,"Ga": 31,"Ge": 32,"As": 33,"Se": 34,"Br": 35,"Kr": 36,
    "Rb": 37,"Sr": 38,"Y": 39, "Zr": 40,"Nb": 41,"Mo": 42,"Tc": 43,"Ru": 44,"Rh": 45,"Pd": 46,
    "Ag": 47,"Cd": 48,"In": 49,"Sn": 50,"Sb": 51,"Te": 52,"I": 53, "Xe": 54,
    "Cs": 55,"Ba": 56,          "Hf": 72,"Ta": 73,"W": 74, "Re": 75,"Os": 76,"Ir": 77,"Pt": 78,
    "Au": 79,"Hg": 80,"Tl": 81,"Pb": 82,"Bi": 83,"Po": 84,"At": 85,"Rn": 86,
    "La": 57,"Ce": 58,"Pr": 59,"Nd": 60,"Pm": 61,"Sm": 62,"Eu": 63,"Gd": 64,
    "Tb": 65,"Dy": 66,"Ho": 67,"Er": 68,"Tm": 69,"Yb": 70,"Lu": 71,
    "Ac": 89,"Th": 90,"Pa": 91,"U": 92, "Np": 93,"Pu": 94,"Am": 95,"Cm": 96,
    "Bk": 97,"Cf": 98,"Es": 99,"Fm": 100,"Md": 101,"No": 102,"Lr": 103
}

def _norm_sym(sym: str) -> str:
    # Handle 'fe'/'FE' → 'Fe', etc.
    return sym[:1].upper() + sym[1:].lower() if sym else sym

def total_electrons(symbols, charge):
    """Sum atomic numbers from EL_TO_Z and subtract net charge."""
    zsum = 0
    for s in symbols:
        zs = EL_TO_Z.get(_norm_sym(s))
        if zs is None:
            raise ValueError(f"Unknown element symbol '{s}'. Please extend EL_TO_Z.")
        zsum += zs
    return zsum - charge

def base_uhf_from_parity(symbols, charge):
    return 0 if (total_electrons(symbols, charge) % 2 == 0) else 1
