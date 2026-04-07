# ── SNIPPET: feature_table_parser/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      ML/ML_all_model.py and ML/ML_single_model.py
# Invariants:
#   - Header row: features are fields[2:-1] (skips name and linker columns).
#   - Labels are binarized: 0 stays 0, any nonzero becomes 1.
# Notes: Used by both ML scripts.
# ────────────────────────────────────────────────────────────

import numpy as np

def data_process(filename,desire_feat_ind=[]):
    data = []
    label = []
    with open(filename,'r') as f:
        for lc,lines in enumerate(f):
            fields = lines.split()
            if lc == 0: 
                if desire_feat_ind == []:
                    features = fields[2:-1] # including all feat, 0: name, 1: linker, -1: label
                else:
                    features = [ fields[_] for _ in desire_feat_ind]
                continue
            if desire_feat_ind == []:
                data.append([float(i) for i in fields[2:-1]])
            else:
                tmp_feat = [ float(fields[_]) for _ in desire_feat_ind]
                data.append(tmp_feat)
            if int(fields[-1]) == 0: 
               label.append(0)
            else:
               label.append(1)

    data = np.array(data)
    label = np.array(label)
    
    return data,label,features
