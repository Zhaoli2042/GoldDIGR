# ── SNIPPET: bem_sanity_checks/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - If BEM missing => warning only; workflow may proceed.
#   - bond_changes == 'no_changes' => hard error.
#   - sigma_count == 0 => warning; constraints will be absent.
# Notes: MAX_BOND_CHANGES threshold is a constant.
# ────────────────────────────────────────────────────────────

MAX_BOND_CHANGES = 10  # Warning threshold for excessive bond changes

def validate_bem_results(bem_r, bem_p,
                         bond_changes: str, sigma_count: int):
    """
    Validate BEM analysis results.
    Returns (is_valid, list_of_warnings_or_errors).
    """
    issues = []
    is_valid = True

    if bem_r is None or bem_p is None:
        issues.append("WARNING: BEM computation failed - cannot validate bond changes")
        # This is a warning, not an error - workflow can proceed with user-provided bond_changes
        return True, issues

    if bond_changes == "no_changes":
        issues.append("ERROR: No bond changes detected between R and P")
        issues.append("  R.xyz and P.xyz may be identical or have the same bonding pattern")
        is_valid = False
        return is_valid, issues

    if sigma_count == 0:
        issues.append("WARNING: No sigma bond changes detected (only pi bond changes)")
        issues.append("  COPT will run without distance constraints")

    if sigma_count > MAX_BOND_CHANGES:
        issues.append(f"WARNING: Large number of sigma bond changes ({sigma_count})")
        issues.append("  This may indicate a problem with the input structures")

    return is_valid, issues
