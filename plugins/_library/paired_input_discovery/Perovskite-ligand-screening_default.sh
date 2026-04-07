# ── SNIPPET: paired_input_discovery/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/step1.build_bulk_sims.py
# Invariants:
#   - Skip any xyz that does not have a same-basename .db file.
# Notes: This is embedded in the driver; extracted as the tested loop logic.
# ────────────────────────────────────────────────────────────

import os

d = './'
files = sorted( [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)) and f.endswith('.xyz') and f not in {{EXCLUDE_XYZS_LIST}}] )

for f in files:
    dir_prefix = f.strip('.xyz')
    print('Working {}...'.format(dir_prefix))
    
    # Check to make sure there isn't a stray .xyz file
    if not os.path.isfile(dir_prefix+'.db'):
            print('   Missing forcefield database file, skipping...')
            continue
