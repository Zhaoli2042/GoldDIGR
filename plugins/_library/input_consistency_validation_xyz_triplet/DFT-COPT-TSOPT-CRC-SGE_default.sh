# ── SNIPPET: input_consistency_validation_xyz_triplet/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Element order must match exactly across files; mismatch is a hard error with first few diffs printed.
#   - Atom count mismatch is a hard error.
# Notes: Used in preprocessing adapter.
# ────────────────────────────────────────────────────────────

from typing import Tuple, List

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

def validate_xyz_files(r_xyz: str, p_xyz: str, ts_xyz: str) -> Tuple[bool, List[str]]:
    """
    Validate that XYZ files are consistent.
    Returns (is_valid, list_of_errors).
    """
    errors = []
    warnings = []

    # Check files exist
    for name, path in [("Reactant", r_xyz), ("Product", p_xyz), ("TS", ts_xyz)]:
        if not os.path.exists(path):
            errors.append(f"{name} file not found: {path}")

    if errors:
        return False, errors

    # Read all files
    try:
        r_elements, r_coords, _ = read_xyz(r_xyz)
        p_elements, p_coords, _ = read_xyz(p_xyz)
        ts_elements, ts_coords, _ = read_xyz(ts_xyz)
    except Exception as e:
        errors.append(f"Error reading XYZ files: {e}")
        return False, errors

    # Check atom counts match
    n_r, n_p, n_ts = len(r_elements), len(p_elements), len(ts_elements)
    if not (n_r == n_p == n_ts):
        errors.append(f"Atom count mismatch: R={n_r}, P={n_p}, TS={n_ts}")
        return False, errors

    # Check elements match (order matters)
    if r_elements != p_elements:
        errors.append("Element mismatch between Reactant and Product")
        # Show first few differences
        for i, (r, p) in enumerate(zip(r_elements, p_elements)):
            if r != p:
                errors.append(f"  Atom {i}: R={r}, P={p}")
                if len([e for e in errors if "Atom" in e]) >= 3:
                    errors.append("  ...")
                    break
        return False, errors

    if r_elements != ts_elements:
        errors.append("Element mismatch between Reactant and TS")
        for i, (r, ts) in enumerate(zip(r_elements, ts_elements)):
            if r != ts:
                errors.append(f"  Atom {i}: R={r}, TS={ts}")
                if len([e for e in errors if "Atom" in e]) >= 3:
                    errors.append("  ...")
                    break
        return False, errors

    return True, []
