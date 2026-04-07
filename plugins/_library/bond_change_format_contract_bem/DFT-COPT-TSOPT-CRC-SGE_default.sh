# ── SNIPPET: bond_change_format_contract_bem/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        yarp | openbabel
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Bond change token format: ElemI{i}-ElemJ{j}:{r_str}>{p_str} with 'n' for no bond.
#   - Sigma change definition uses integer orders: 0->>0 or >0->0.
# Notes: Used to seed workflow_status.json.
# ────────────────────────────────────────────────────────────

import numpy as np
from typing import List, Tuple

def is_sigma_bond_change(old_order: int, new_order: int) -> bool:
    """
    Determine if a bond change represents a sigma bond change.
    Sigma bond changes: formation (0->1) or breaking (1->0)
    NOT sigma: pi bond changes (1->2, 2->1, 2->3, etc.)
    """
    # n (no bond, 0) to any bond order = sigma formation
    if old_order == 0 and new_order > 0:
        return True
    # any bond order to n (0) = sigma breaking
    if old_order > 0 and new_order == 0:
        return True

    return False


def format_bond_changes(bem_r: np.ndarray, bem_p: np.ndarray,
                        elements: List[str]) -> Tuple[str, int]:
    """
    Format bond changes between reactant and product BEMs.
    Returns (bond_changes_string, sigma_change_count).

    Format: "C12-H30:n>1;H30-Ir0:1>n"
    """
    if bem_r is None or bem_p is None:
        return "N/A", 0

    changes = []
    sigma_count = 0
    n_atoms = len(elements)

    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            r_order = int(bem_r[i, j])
            p_order = int(bem_p[i, j])

            if r_order != p_order:
                r_str = str(r_order) if r_order > 0 else "n"
                p_str = str(p_order) if p_order > 0 else "n"
                changes.append(f"{elements[i]}{i}-{elements[j]}{j}:{r_str}>{p_str}")

                if is_sigma_bond_change(r_order, p_order):
                    sigma_count += 1

    return (";".join(changes) if changes else "no_changes", sigma_count)
