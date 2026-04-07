# ── SNIPPET: xyz_trajectory_read_multi/last_frame_extraction_for_restart ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Notes: Useful for ROUND2/resume patterns.
# ────────────────────────────────────────────────────────────

import os
from typing import List, Tuple, Optional
import numpy as np

def parse_multi_xyz(filepath: str) -> List[Tuple[List[str], np.ndarray, str]]:
    """Parse multi-frame XYZ file (trajectory)."""
    frames = []
    with open(filepath, 'r') as f:
        content = f.read()

    lines = content.strip().split('\n')
    i = 0
    while i < len(lines):
        try:
            n_atoms = int(lines[i].strip())
        except (ValueError, IndexError):
            break

        comment = lines[i + 1].strip() if i + 1 < len(lines) else ""
        elements = []
        coords = []

        for j in range(i + 2, min(i + 2 + n_atoms, len(lines))):
            parts = lines[j].split()
            if len(parts) >= 4:
                elements.append(parts[0])
                coords.append([float(x) for x in parts[1:4]])

        if len(elements) == n_atoms:
            frames.append((elements, np.array(coords), comment))

        i += 2 + n_atoms

    return frames


def get_last_geometry_from_trj(trj_file: str, output_xyz: str) -> Optional[str]:
    """Extract last frame from trajectory file."""
    if not os.path.exists(trj_file):
        return None

    frames = parse_multi_xyz(trj_file)
    if not frames:
        return None

    elements, coords, comment = frames[-1]
    write_xyz(output_xyz, elements, coords, comment)
    return output_xyz
