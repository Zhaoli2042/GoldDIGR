# ── SNIPPET: ts_guess_generation_and_seed_files/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - ts_guess.xyz is a direct copy of provided TS geometry (no modification).
#   - Always write workflow_status.json into output_dir.
# Notes: This is the core of xyz_prep.py’s processing.
# ────────────────────────────────────────────────────────────

import os, json, shutil
from typing import Tuple, Dict

def process_xyz_inputs(r_xyz: str, p_xyz: str, ts_xyz: str,
                       charge: int, mult: int,
                       output_dir: str) -> Tuple[Dict, str]:
    """
    Process XYZ inputs and generate workflow files.
    Returns (workflow_status, ts_guess_path).
    """
    print("=" * 60)
    print("XYZ Preprocessing for DFT Verification")
    print("=" * 60)
    print(f"Reactant: {r_xyz}")
    print(f"Product:  {p_xyz}")
    print(f"TS:       {ts_xyz}")
    print(f"Charge:   {charge}")
    print(f"Mult:     {mult}")
    print(f"Output:   {output_dir}")
    print()

    # Validate XYZ files
    print("Validating input files...")
    is_valid, errors = validate_xyz_files(r_xyz, p_xyz, ts_xyz)
    if not is_valid:
        for err in errors:
            print(f"  {err}")
        raise ValidationError("Input validation failed")
    print("  XYZ files validated successfully")

    # Read elements for BEM analysis
    elements, _, _ = read_xyz(r_xyz)
    print(f"  Atom count: {len(elements)}")

    # Compute BEMs
    print("\nComputing Bond Electron Matrices...")
    bem_r = get_yarp_bem(r_xyz, charge)
    bem_p = get_yarp_bem(p_xyz, charge)

    if bem_r is not None:
        print("  Reactant BEM: computed")
    else:
        print("  Reactant BEM: FAILED")

    if bem_p is not None:
        print("  Product BEM: computed")
    else:
        print("  Product BEM: FAILED")

    # Detect bond changes
    print("\nAnalyzing bond changes...")
    bond_changes, sigma_count = format_bond_changes(bem_r, bem_p, elements)
    print(f"  Bond changes: {bond_changes}")
    print(f"  Sigma bond changes: {sigma_count}")

    # Validate BEM results
    is_valid, issues = validate_bem_results(bem_r, bem_p, bond_changes, sigma_count)
    for issue in issues:
        print(f"  {issue}")

    if not is_valid:
        raise ValidationError("BEM validation failed")

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Copy TS to ts_guess.xyz
    ts_guess_path = os.path.join(output_dir, "ts_guess.xyz")
    shutil.copy2(ts_xyz, ts_guess_path)
    print(f"\nCopied TS to: {ts_guess_path}")

    # Also copy R and P for reference
    shutil.copy2(r_xyz, os.path.join(output_dir, "R.xyz"))
    shutil.copy2(p_xyz, os.path.join(output_dir, "P.xyz"))

    # Create workflow_status.json
    workflow_status = create_workflow_status(r_xyz, p_xyz, ts_xyz, charge, mult, bond_changes)

    ws_path = os.path.join(output_dir, "workflow_status.json")
    with open(ws_path, 'w') as f:
        json.dump(workflow_status, f, indent=2)
    print(f"Created: {ws_path}")

    return workflow_status, ts_guess_path
