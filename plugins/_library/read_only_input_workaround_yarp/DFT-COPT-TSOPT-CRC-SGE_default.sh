# ── SNIPPET: read_only_input_workaround_yarp/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        yarp | openbabel
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Probe write access by creating/removing a .write_test file in the input directory.
#   - If not writable, copy XYZ to tempfile.mkdtemp and run YARP there; always cleanup temp dir.
# Notes: This is embedded in get_yarp_bem; keep behavior.
# ────────────────────────────────────────────────────────────

def get_yarp_bem(xyz_path: str, charge: int):
    """
    Get Bond Electron Matrix using YARP.
    Returns None if YARP is not available or fails.
    """
    import tempfile
    import shutil
    import numpy as np
    import os, sys

    # Add YARP to path (container location)
    yarp_paths = ['/opt/yarp', '/opt/workflow', '/opt/yarp/yarp_custom']
    for yarp_path in yarp_paths:
        if os.path.exists(yarp_path) and yarp_path not in sys.path:
            sys.path.insert(0, yarp_path)

    # YARP writes temp files in the same directory as input
    # If input is read-only, we need to copy to a temp location
    temp_dir = None
    working_xyz = xyz_path

    try:
        # Check if we can write to the input directory
        input_dir = os.path.dirname(xyz_path)
        test_file = os.path.join(input_dir, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except (OSError, IOError):
            # Read-only - copy to temp
            temp_dir = tempfile.mkdtemp(prefix='yarp_')
            working_xyz = os.path.join(temp_dir, os.path.basename(xyz_path))
            shutil.copy2(xyz_path, working_xyz)
            print(f"  Copied to temp dir for YARP: {temp_dir}")
    except Exception as e:
        print(f"  Warning: Could not check write access: {e}")

    bem = None

    # Try yarp_helpers first
    try:
        from yarp_helpers import silent_yarpecule, labelled_matrix
        mol = silent_yarpecule(working_xyz, charge)
        bem = labelled_matrix(mol)
        print("  Success with yarp_helpers!")
    except ImportError as e:
        print(f"  yarp_helpers import failed: {e}")
    except Exception as e:
        print(f"  yarp_helpers failed: {type(e).__name__}: {e}")

    # Fallback to direct YARP import
    if bem is None:
        try:
            from yarpecule import Yarpecule
            mol = Yarpecule(working_xyz, q=charge)
            bem = mol.bond_mats()[0]
            print("  Success with Yarpecule!")
        except ImportError as e:
            print(f"  Yarpecule import failed: {e}")
        except Exception as e:
            print(f"  Yarpecule failed: {type(e).__name__}: {e}")

    # Fallback to OpenBabel
    if bem is None:
        try:
            from openbabel import openbabel as ob

            elements, coords, _ = read_xyz(working_xyz)
            n_atoms = len(elements)

            obconv = ob.OBConversion()
            obconv.SetInFormat("xyz")
            mol = ob.OBMol()
            obconv.ReadFile(mol, working_xyz)
            mol.SetTotalCharge(charge)

            bem = np.zeros((n_atoms, n_atoms), dtype=int)
            for bond in ob.OBMolBondIter(mol):
                i = bond.GetBeginAtomIdx() - 1
                j = bond.GetEndAtomIdx() - 1
                order = bond.GetBondOrder()
                bem[i, j] = order
                bem[j, i] = order

            print("  Success with OpenBabel!")
        except ImportError as e:
            print(f"  OpenBabel import failed: {e}")
        except Exception as e:
            print(f"  OpenBabel failed: {type(e).__name__}: {e}")

    # Cleanup temp directory
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    if bem is None:
        print("  WARNING: All BEM methods failed!")

    return bem
