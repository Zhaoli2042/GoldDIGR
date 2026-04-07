# ── SNIPPET: smiles_prefix_map_rehydration/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      get_auto3d_calc_status
# Invariants:
#   - Input lines are split on whitespace; first token is SMILES.
#   - If prefix missing, uses 'NO_PREFIX'.
#   - If file missing, returns empty mapping.
# Notes: Enables writing failed/missing lists as 'SMILES PREFIX'.
# ────────────────────────────────────────────────────────────

import os
from typing import Dict

def load_smiles_prefix_map(file_path: str) -> Dict[str, str]:
    """
    Reads the original input file and returns a dict: {SMILES: PREFIX}.
    """
    mapping = {}
    if not file_path or not os.path.exists(file_path):
        return mapping
    
    with open(file_path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                smi = parts[0]
                prefix = parts[1] if len(parts) > 1 else "NO_PREFIX"
                mapping[smi] = prefix
    return mapping
