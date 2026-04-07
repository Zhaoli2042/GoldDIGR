# ── SNIPPET: metal_detection_by_element_set/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Metal detection uses element symbol capitalization and membership in METALS set.
#   - Neighbor detection uses a fixed 3.0 Å cutoff and is informational only.
# Notes: Neighbor indices are not used for reactive atom selection in this pipeline.
# ────────────────────────────────────────────────────────────

from typing import Set, Tuple
import numpy as np

METALS = {
    'Li', 'Be', 'Na', 'Mg', 'Al', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn',
    'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo',
    'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Cs', 'Ba', 'La', 'Ce',
    'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb',
    'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb',
    'Bi', 'Po', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm',
    'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr'
}

def get_metal_and_neighbors(xyz_path: str) -> Tuple[Set[int], Set[int]]:
    """
    Get metal atom indices and their neighbor indices.
    Returns (metal_indices, neighbor_indices).
    Note: Neighbors are for reference only - reactive atoms are determined separately.
    """
    elements, coords, _ = read_xyz(xyz_path)

    metal_indices = set()
    for i, elem in enumerate(elements):
        if elem.capitalize() in METALS:
            metal_indices.add(i)

    # Find neighbors within bonding distance (for informational purposes)
    neighbor_indices = set()
    for m_idx in metal_indices:
        m_coord = coords[m_idx]
        for j, coord in enumerate(coords):
            if j != m_idx:
                dist = np.linalg.norm(m_coord - coord)
                if dist < 3.0:  # Within typical bonding range
                    neighbor_indices.add(j)

    return metal_indices, neighbor_indices
