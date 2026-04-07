# ── SNIPPET: zip_member_find_by_suffix/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Suffix matching is used (not exact path), enabling variable leading directories inside zips.
#   - xTB-scan lookup requires member name ending with 'xTB-scan/<filename>'.
# Notes: Keeps zip reading selective and robust to archive layout.
# ────────────────────────────────────────────────────────────

from typing import List, Optional

def find_member(namelist: List[str], suffix: str) -> Optional[str]:
    """Return the first member whose name ends with the given suffix, or None."""
    for name in namelist:
        if name.endswith(suffix):
            return name
    return None

def find_xtb_scan_member(namelist: List[str], filename: str) -> Optional[str]:
    """Return the member inside an xTB-scan/ folder with the given basename."""
    suffix = f"xTB-scan/{filename}"
    for name in namelist:
        if name.endswith(suffix):
            return name
    return None
