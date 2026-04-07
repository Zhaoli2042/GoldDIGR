# ── SNIPPET: config_key_validation/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/functions.py
# Invariants:
#   - Lines starting with # are comments; inline comments after # are stripped.
#   - Abort if any required setting is missing.
#   - Cast JOB_MD_PPN/JOB_MD_NODES/JOB_MD_WALLTIME to int.
# Notes: Required keys are workflow-specific; keep the list as-is unless you also update downstream consumers.
# ────────────────────────────────────────────────────────────

import os

# Reads and processes a config file
def read_config(config_file):

    # Check to make sure the trajectory xyz file exists.
    if not os.path.isfile(config_file):
        print('\nERROR: Specified configuration file file "{}" not found. Aborting....\n'.format(config_file))
        exit()
    
    config = {}
    with open(config_file, 'r') as f:
        for line in f:
            
            # Skip comment lines and omit any inline comments
            if line[0] == '#':
                continue
            if '#' in line:
                line = line.split('#')[0]
            
            fields = line.split()
            if len(fields) > 0 :
                if fields[0].upper() not in list(config.keys()):
                    config[fields[0].upper()] = ' '.join(fields[1:])
    
    settings = ['JOB_MD_PPN', 'JOB_MD_NODES', 'JOB_MD_WALLTIME', 'JOB_MD_QUEUE','LAMMPS_PATH']
    
    missing = False
    for s in settings:
        if s not in list(config.keys()):
            print('ERROR: Missing setting {} in configuration file.'.format(s))
            missing = True
    if missing:
        print('Aborting...')
        exit()
        
    settings = ['JOB_MD_PPN', 'JOB_MD_NODES', 'JOB_MD_WALLTIME']
    for s in settings:
        config[s] = int(config[s])
    
    
    return config
