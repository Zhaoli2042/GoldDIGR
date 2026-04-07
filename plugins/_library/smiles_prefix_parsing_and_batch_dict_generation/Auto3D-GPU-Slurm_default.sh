# ── SNIPPET: smiles_prefix_parsing_and_batch_dict_generation/Auto3D-GPU-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Invariants:
#   - Input format is whitespace-separated: 'SMILES PREFIX' (PREFIX optional).
#   - Batch dict value packs two fields using BATCH_DICT_SEPARATOR: 'out_dir:::prefix'.
#   - Output directories are index-based (str(i)) to keep stable layout across runs.
# Notes: This is the core chunk-management block for large SMILES lists.
# ────────────────────────────────────────────────────────────

from typing import Dict, List

def generate_batch_dicts(smiles_list_path: str, smiles_done_set: set, batch_size: int) -> List[Dict[str, str]]:
    raw_lines = read_unique_lines(smiles_list_path)

    # Parse lines into (SMILES, PREFIX)
    smiles_data = []
    for line in raw_lines:
        parts = line.split()
        if not parts:
            continue
        smi = parts[0]
        prefix = parts[1] if len(parts) > 1 else f"MOL_{len(smiles_data)}"
        smiles_data.append((smi, prefix))

    # Determine paths; store both path and prefix in the value, separated by constant
    smiles_to_do_dict = {}
    for i, (smiles, prefix) in enumerate(smiles_data):
        if smiles not in smiles_done_set:
            out_dir = os.path.join(GEO_DATA_OUT_PATH_MAIN, str(i))
            val = f"{out_dir}{BATCH_DICT_SEPARATOR}{prefix}"
            smiles_to_do_dict[smiles] = val

    smiles_keys = list(smiles_to_do_dict.keys())
    batch_dicts: List[Dict[str, str]] = []
    for i in range(0, len(smiles_keys), batch_size):
        batch = {s: smiles_to_do_dict[s] for s in smiles_keys[i:i + batch_size]}
        if batch:
            batch_dicts.append(batch)
    return batch_dicts
