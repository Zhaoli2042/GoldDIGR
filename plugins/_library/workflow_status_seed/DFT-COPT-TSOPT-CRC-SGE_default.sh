# ── SNIPPET: workflow_status_seed/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - input_data must include charge, mult, bond_changes, and source for provenance.
#   - preprocessing.status is 'success' when created by adapter.
# Notes: Downstream workflow reads input_data.bond_changes.
# ────────────────────────────────────────────────────────────

import os
from typing import Dict

def create_workflow_status(r_xyz: str, p_xyz: str, ts_xyz: str,
                           charge: int, mult: int,
                           bond_changes: str) -> Dict:
    """Create workflow_status.json content."""
    workflow_status = {
        "input_data": {
            "charge": charge,
            "mult": mult,
            "bond_changes": bond_changes,
            "source": "xyz_prep.py",
            "reactant_xyz": os.path.basename(r_xyz),
            "product_xyz": os.path.basename(p_xyz),
            "ts_xyz": os.path.basename(ts_xyz)
        },
        "preprocessing": {
            "status": "success",
            "method": "YARP BEM analysis"
        }
    }

    return workflow_status
