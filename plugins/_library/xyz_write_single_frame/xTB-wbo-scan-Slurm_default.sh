# ── SNIPPET: xyz_write_single_frame/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Always writes natoms line then comment line then natoms coordinate lines.
#   - Coordinates are formatted with 8 decimals.
# Notes: Used to materialize per-frame geometries for xTB.
# ────────────────────────────────────────────────────────────

def write_xyz(symbols, coords, outpath, comment=""):
    with open(outpath, "w") as f:
        f.write(f"{len(symbols)}\n")
        f.write(f"{comment}\n")
        for s,(x,y,z) in zip(symbols, coords):
            f.write(f"{s:2s} {x: .8f} {y: .8f} {z: .8f}\n")
