# ── SNIPPET: threshold_based_classification/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/step3.collect_stabilities.py
# Invariants:
#   - bond_lqe_diff is abs(1.0 - bond_lqe_avg).
#   - angle_var_diff is abs(angle_var_avg) (ideal 0).
#   - Formed=2 if both pass; Formed+Disordered=1 if bond passes but angle fails; else 0.
# Notes: This is the core labeling logic used for downstream ML.
# ────────────────────────────────────────────────────────────

# Compute avergae bond_lqe, then compute difference from ideal bond_lqe (=1.0) for use evaluating
if len(Results[d]['bond_lqe']) > 0:
    Results[d]['bond_lqe_avg']    = sum(Results[d]['bond_lqe'])/len(Results[d]['bond_lqe'])
    Results[d]['bond_lqe_diff']   = abs(1.0 - Results[d]['bond_lqe_avg'])
    Results[d]['bond_lqe_check']  = True if Results[d]['bond_lqe_diff'] <= bond_lqe_cutoff else False
else:
    Results[d]['problematic']    = True
                
# Compute average angle_var, then use this for evaluating (ideal angle_var = 0.0)
if len(Results[d]['angle_var']) > 0:
    Results[d]['angle_var_avg']    = sum(Results[d]['angle_var'])/len(Results[d]['angle_var'])
    Results[d]['angle_var_diff']   = abs(Results[d]['angle_var_avg'])
    Results[d]['angle_var_check']  = True if Results[d]['angle_var_diff'] <= angle_var_cutoff else False
else:
    Results[d]['problematic']    = True

# Evaluate stability of ligand
if not Results[d]['problematic']:
    if Results[d]['bond_lqe_check'] and Results[d]['angle_var_check']:
        Results[d]['comments'] = 'True'
        Results[d]['formed']   = True
        stability_label = 2
    elif Results[d]['bond_lqe_check'] and not Results[d]['angle_var_check']:
        Results[d]['comments']   = 'Most likely true: octahedron may be a bit distorted as angles are enlarged'
        Results[d]['formed']     = True
        Results[d]['disordered'] = True
        stability_label = 1
    elif not Results[d]['bond_lqe_check'] and Results[d]['angle_var_check']:
        Results[d]['comments'] = 'False'
        Results[d]['formed']   = False
        stability_label = 0
    else:
        Results[d]['comments'] = 'False'
        Results[d]['formed']   = False
        stability_label = 0
else:
    Results[d]['comments'] = 'Issue with this ligand, missing bond_lqe and/or angle_var data.'
