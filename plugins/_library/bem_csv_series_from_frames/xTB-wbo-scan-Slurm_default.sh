# ── SNIPPET: bem_csv_series_from_frames/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Frame index is parsed from filename token frame_00088_bond_electrons.csv → 88.
#   - If labels differ across frames, conservatively reorder by label name into the first-frame label order; missing labels become 0.0.
# Notes: Downstream assumes mats[0] is first frame and mats[-1] is last.
# ────────────────────────────────────────────────────────────

from pathlib import Path
from glob import glob

def _series_from_frames(workdir):
    """
    Load all frame_#####_bond_electrons.csv in workdir, sorted by frame index.
    Returns: labels, [mat0, mat1, ...], [frame_indices]
    """
    files = sorted(glob(str(Path(workdir)/"frame_*_bond_electrons.csv")))
    if not files:
        return [], [], []
    # sort by numeric frame
    def _frame_idx(p):
        name = Path(p).name
        # frame_00088_bond_electrons.csv → 00088
        return int(name.split("_")[1])
    files.sort(key=_frame_idx)
    labels0, mat0 = _load_bem_e_csv(files[0])
    mats = [mat0]
    frames = [_frame_idx(files[0])]
    for fp in files[1:]:
        lab, m = _load_bem_e_csv(fp)
        # ensure label consistency; if not, intersect in order
        if lab != labels0:
            # conservative: map by name
            idx_map = {lab: i for i, lab in enumerate(lab)}
            reorder = [idx_map.get(L, None) for L in labels0]
            mm = [[0.0]*len(labels0) for _ in range(len(labels0))]
            for i, src_i in enumerate(reorder):
                if src_i is None: continue
                for j, src_j in enumerate(reorder):
                    if src_j is None: continue
                    mm[i][j] = m[src_i][src_j]
            m = mm
        mats.append(m)
        frames.append(_frame_idx(fp))
    return labels0, mats, frames
