# ── SNIPPET: ts_frame_from_finished_irc_trj/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Energy is parsed from the first token of the XYZ comment line.
#   - TS is defined as argmax energy ignoring NaNs.
#   - Parsing stops when natoms line cannot be parsed as int.
# Notes: Designed for finished_irc.trj inside zip archives.
# ────────────────────────────────────────────────────────────

import math
from typing import List, Optional, Tuple

def parse_ts_from_trj(file_bytes: bytes) -> Tuple[Optional[int], Optional[float], int]:
    """Parse finished_irc.trj content and return (ts_frame_idx, ts_energy, n_frames).

    The file is assumed to contain repeated XYZ blocks:
        line 1: integer number of atoms
        line 2: energy (float, possibly followed by comments)
        next N lines: coordinates

    The TS frame is defined as the frame with the highest energy.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()

    energies: List[float] = []
    i = 0
    frame_idx = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        try:
            natoms = int(line)
        except ValueError:
            # If we can't parse natoms here, stop parsing further
            break
        if i + 1 >= len(lines):
            break
        energy_line = lines[i + 1].strip()
        tokens = energy_line.split()
        if not tokens:
            energy = float("nan")
        else:
            try:
                energy = float(tokens[0])
            except ValueError:
                energy = float("nan")
        energies.append(energy)
        # Skip coordinates: N atom lines
        i += 2 + natoms
        frame_idx += 1

    n_frames = len(energies)
    if n_frames == 0:
        return None, None, 0

    # Find index of max energy, ignoring NaNs
    valid_indices = [idx for idx, e in enumerate(energies) if not math.isnan(e)]
    if not valid_indices:
        return None, None, n_frames
    ts_idx = max(valid_indices, key=lambda idx: energies[idx])
    ts_energy = energies[ts_idx]
    return ts_idx, ts_energy, n_frames
