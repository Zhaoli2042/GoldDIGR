# ── SNIPPET: xyz_write_single_frame/minimal_xyz_read_and_write_with_comment_roundtrip ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Notes: Appears in both scripts; keep identical behavior.
# ────────────────────────────────────────────────────────────

from typing import List, Tuple
import numpy as np

def read_xyz(filepath: str) -> Tuple[List[str], np.ndarray, str]:
    """Read XYZ file, return elements, coordinates, and comment line."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    n_atoms = int(lines[0].strip())
    comment = lines[1].strip() if len(lines) > 1 else ""

    elements = []
    coords = []
    for i in range(2, 2 + n_atoms):
        parts = lines[i].split()
        elements.append(parts[0])
        coords.append([float(x) for x in parts[1:4]])

    return elements, np.array(coords), comment


def write_xyz(filepath: str, elements: List[str], coords: np.ndarray, comment: str = ""):
    """Write XYZ file."""
    with open(filepath, 'w') as f:
        f.write(f"{len(elements)}\n")
        f.write(f"{comment}\n")
        for elem, coord in zip(elements, coords):
            f.write(f"{elem:4s} {coord[0]:15.8f} {coord[1]:15.8f} {coord[2]:15.8f}\n")
