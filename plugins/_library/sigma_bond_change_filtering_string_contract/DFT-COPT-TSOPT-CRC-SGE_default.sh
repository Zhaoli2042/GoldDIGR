# ── SNIPPET: sigma_bond_change_filtering_string_contract/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Sigma change definition: n->(not n) or (not n)->n; pi changes are excluded.
#   - Bond change string format must match regex: ElemIIdx-ElemJIdx:old>new separated by ';'.
# Notes: Used to drive constraints and basis focusing.
# ────────────────────────────────────────────────────────────

import re
from typing import List, Tuple, Set, Dict

def is_sigma_bond_change(old_order: str, new_order: str) -> bool:
    """
    Determine if a bond change represents a sigma bond change.
    Sigma bond changes: formation (n->1) or breaking (1->n)
    NOT sigma: pi bond changes (1->2, 2->1, 2->3, etc.)
    """
    old = old_order.strip().lower()
    new = new_order.strip().lower()

    # n (no bond) to any bond order = sigma formation
    if old == 'n' and new != 'n':
        return True
    # any bond order to n = sigma breaking
    if old != 'n' and new == 'n':
        return True

    return False


def parse_bond_changes_for_constraints(bond_changes_str: str) -> List[Tuple[int, int]]:
    """
    Parse bond changes string and return atom pairs involved in sigma bond changes.
    Example: "C12-H30:n>1;H30-Ir0:1>n" -> [(12, 30), (30, 0)]
    """
    if not bond_changes_str or bond_changes_str == "N/A":
        return []

    constraints = []
    changes = bond_changes_str.split(';')

    for change in changes:
        change = change.strip()
        if not change:
            continue

        match = re.match(r'([A-Za-z]+)(\d+)-([A-Za-z]+)(\d+):(\S+)>(\S+)', change)
        if match:
            elem1, idx1, elem2, idx2, old_order, new_order = match.groups()
            idx1, idx2 = int(idx1), int(idx2)

            if is_sigma_bond_change(old_order, new_order):
                constraints.append((idx1, idx2))

    return constraints


def parse_bond_changes(bond_changes_str: str) -> Set[int]:
    """
    Parse bond changes string and return set of atom indices involved.
    Example: "C12-H30:n>1;H30-Ir0:1>n" -> {0, 12, 30}
    """
    if not bond_changes_str or bond_changes_str == "N/A":
        return set()

    atom_indices = set()
    changes = bond_changes_str.split(';')

    for change in changes:
        change = change.strip()
        if not change:
            continue

        match = re.match(r'([A-Za-z]+)(\d+)-([A-Za-z]+)(\d+):(\S+)>(\S+)', change)
        if match:
            elem1, idx1, elem2, idx2, old_order, new_order = match.groups()
            # Only include atoms from sigma bond changes
            if is_sigma_bond_change(old_order, new_order):
                atom_indices.add(int(idx1))
                atom_indices.add(int(idx2))

    return atom_indices


def get_sigma_bond_constraints(workflow_status: Dict) -> List[Tuple[int, int]]:
    """Get sigma bond constraints from workflow_status."""
    bond_changes = workflow_status.get('input_data', {}).get('bond_changes', '')
    return parse_bond_changes_for_constraints(bond_changes)


def get_reactive_atoms(workflow_status: Dict) -> Set[int]:
    """
    Get reactive atoms from workflow_status.
    Reactive atoms = atoms involved in sigma bond changes.
    """
    bond_changes = workflow_status.get('input_data', {}).get('bond_changes', '')
    return parse_bond_changes(bond_changes)
