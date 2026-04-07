# ── SNIPPET: slurm_submission_template_with_modules/Perovskite-ligand-screening_default ─
# Scheduler:   slurm
# Tool:        lammps
# Tested:      MD/lib/functions_writers.py
# Invariants:
#   - Uses Slurm directives: --job-name, -N, -n, -t, -A, -o, -e.
#   - Loads site modules (gcc/openmpi/etc.) exactly as written.
# Notes: The provided file is truncated in the bundle; keep as-is and fill remaining run command at integration time.
# ────────────────────────────────────────────────────────────

import os

def make_LAMMPS_submission(lammps_init, job_name, nodes, ppn, queue, walltime, \
                           lammps_exe=None, \
                           resub=0, repeat=0, output='submit.sh', log_name='LAMMPS_run.out'):
    
    with open(output, 'w') as o:
    
        o.write('#!/bin/sh\n')
        o.write('#SBATCH --job-name={}\n'.format(job_name))
         
        o.write('#SBATCH -N {}\n'.format(nodes))
        o.write('#SBATCH -n {}\n'.format(ppn))
       
        o.write('#SBATCH -t {}:00:00\n'.format(walltime))
        o.write('#SBATCH -A {}\n'.format(queue))
         
         
        o.write('#SBATCH -o {}.out\n'.format(job_name))
        o.write('#SBATCH -e {}.err\n'.format(job_name))
         
        
        
        o.write('\n# Load default LAMMPS, compiler, and openmpi packages\n')
        o.write("module load gcc/9.3.0 \n")  
        o.write("module load openmpi/3.1.4 \n") 
        o.write("module load ffmpeg/4.2.2  \n")
        o.write("module load  openblas/0.3.8  \n")
        o.write("module load  gsl/2.4  \n\n")
        
        o.write('\n# cd into the submission directory\n')
        o.write('cd {}\n'.format(os.getcwd()))
        o.write('echo Working directory is {}\n'.format(os.getcwd()))
        o.write('echo Running on host `hostname`\necho Time ')
