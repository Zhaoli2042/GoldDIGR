# ── SNIPPET: replicate_runs_directory_fanout/Perovskite-ligand-screening_default ─
# Scheduler:   slurm
# Tool:        lammps
# Tested:      MD/step1.build_bulk_sims.py
# Invariants:
#   - Never overwrite an existing run directory; skip it.
#   - Each run gets its own eval.in.init and submit.sh.
# Notes: Uses functions.cd and functions_writers.
# ────────────────────────────────────────────────────────────

import os, shutil, subprocess
import functions
import functions_writers

with functions.cd( {{DIR_PREFIX}} ):
    if not os.path.isfile({{DIR_PREFIX}}+'.data'):
        print('   Missing simulation data file, skipping...')
    if not os.path.isfile({{DIR_PREFIX}}+'.in.settings'):
        print('   Missing simulation settings file, skipping...')
                
    # create jobs for each run
    for i in range({{START}}, {{END}}+1):
        if os.path.isdir('run{}'.format(i)):
            print('Run directory run{} already exists, skipping to avoid overwritting files.'.format(i))
            continue
                    
        os.mkdir('run{}'.format(i))
        shutil.copy({{DIR_PREFIX}}+'.data', 'run{}'.format(i))
        shutil.copy({{DIR_PREFIX}}+'.in.settings', 'run{}'.format(i))
                
        with functions.cd ( 'run{}'.format(i) ):
            c = functions_writers.write_LAMMPS_init({{DIR_PREFIX}}, data_name={{DATA_NAME}}, timesteps_npt=100000, timesteps_nvt=100000, nve_cycles=1, pressure_axis='x z', output='eval.in.init')
            if not c:
                print('Error writing input script for NVT job. Aborting...')
                exit()
                    
            c = functions_writers.make_LAMMPS_submission('eval.in.init', 'ML_{}_r{}'.format({{BASENAME}}, i,), {{JOB_MD_NODES}}, {{JOB_MD_PPN}}, {{JOB_MD_QUEUE}}, {{JOB_MD_WALLTIME}}, lammps_exe={{LAMMPS_PATH}})
            if not c:
                print('Error writing submission script. Aborting...')
                exit()
                    
            submission_ID = subprocess.check_output('sbatch submit.sh', shell=True)
            print('Created and submitted ML_{}_r{}. JobID: {}'.format({{BASENAME}}, i, submission_ID))
