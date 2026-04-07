# ── SNIPPET: parameterized_lammps_input_template/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        lammps
# Tested:      MD/lib/functions_writers.py
# Invariants:
#   - Pressure axis must be one of iso/x/y/z; kspace must be ewald or pppm; TIP4P cannot be used with ewald.
#   - Writes variables for run counter and self-edits the input file to increment run.
#   - Writes restart and data at end: extend.end.restart / extend.end.data.
# Notes: This is the exact writer used by step1.build_bulk_sims.py.
# ────────────────────────────────────────────────────────────

import random
import os

def write_LAMMPS_init(name, data_name=None, temperature=298.0, pressure=1.0, pressure_axis='y', timesteps_npt=1000000, \
                      timesteps_nvt=1000000, nve_cycles=0, nve_dist=0.01, extension_number=0, tether=None, tether_types=None, \
                      avg_freq=1000, coords_freq=1000, thermo_freq=1000, dump4avg=1, fixes=None, commands=None, tip4p=None, \
                      kspace='pppm', submission_manager='SLURM', output='nvt.in.init', flag_velocities=False, \
                      flag_ecoh=False, neighbor_build=0, submit_file='submit.sh'):

    if tether != None:
        tether = tether.split()
        if tether[0] not in ['xyz', 'xy', 'xz', 'yz', 'x', 'y', 'z']:
            print('ERROR: Direction for -tether not recognized. Accepts only LAMMPS values:  xyz, xy, xz, yz, x, y, or z. Exiting...')
            return False
        if '.' not in tether[-1]:
            tether.append('100.0')
    
    if tether_types != None:
        tether_types = tether_types.split()
        if tether_types[0] not in ['xyz', 'xy', 'xz', 'yz', 'x', 'y', 'z']:
            print('ERROR: Direction for -tether not recognized. Accepts only LAMMPS values:  xyz, xy, xz, yz, x, y, or z. Exiting...')
            return False
        if '.' not in tether_types[-1]:
            tether_types.append('5.0')
    
    if fixes != None:
        fixes = fixes.split('|')
    
    if commands != None:
        commands = commands.split('|')

    if data_name == None:
        data_name = name + '_nve.end.data'
    
    pressure_axis = pressure_axis.split()
    exit_flag = False
    for axis in pressure_axis:
        if axis not in ['iso', 'x', 'y', 'z']:
            print('ERROR: Specified pressure axis ({}) not recognized. Exiting....'.format(axis))
            exit_flag = True
    if exit_flag: return False
    
    if kspace.lower() not in ['ewald', 'pppm']:
        print('ERROR: kspace style ("{}") not recognized. Exiting...'.format(kspace))
        return False
    
    if tip4p != None and kspace.lower() == 'ewald':
        print('ERROR: Cannot use the ewald kspace style with the TIP4P water model. Exiting...')
        return False
    
    if submission_manager.upper() not in ['SLURM', 'PBS']:
        print('ERROR: Submission manager not recognized. Accepts SLURM, PBS. Exiting...')
        return False

    with open(output, 'w') as o:
        o.write('# LAMMPS input file for perovskite\n')
        o.write('\n')
        o.write('# VARIABLES\n')
        o.write('variable        data_name       index   {}\n'.format(data_name))
        o.write('variable        restart_name    index   extend.end.restart\n')
        o.write('variable        extend_name     index   extend.end.data\n')
        o.write('variable        settings_name   index   {}.in.settings\n'.format(name))
        o.write('variable        nSteps_NPT      index   {}\n'.format(timesteps_npt))
        o.write('variable        nSteps_NVT      index   {}\n'.format(timesteps_nvt))
        o.write('variable        avg_freq        index   {}\n'.format(avg_freq))
        o.write('variable        coords_freq     index   {}\n'.format(coords_freq))
        o.write('variable        thermo_freq     index   {}\n'.format(thermo_freq))
        o.write('variable        dump4avg        index   {}\n'.format(dump4avg))
        o.write('variable        Temp            index   {}\n'.format(temperature))
        o.write('variable        pressure        index   {}\n'.format(pressure))
        for i in range(nve_cycles):
            o.write('variable        vseed{}          index   {}\n'.format(i+1, int(random.random()*100000)))
        if flag_velocities:
            o.write('variable        vseed           index   {}\n'.format(int(random.random()*100000)))
        o.write('variable        run             index   0\n\n')

        o.write('# Change the name of the log output #\n')
        o.write('log ${run}.eval.log\n\n')

        o.write('#===========================================================\n')
        o.write('# GENERAL PROCEDURES\n')
        o.write('#===========================================================\n')
        o.write('units\t\treal   # g/mol, angstroms, fs, kcal/mol, K, atm, charge*angstrom\n')
        o.write('dimension\t3      # 3 dimensional simulation\n')
        if tip4p != None:
            o.write('newton\t\ton  \t# use Newton\'s 3rd law\n')
        else:
            o.write('newton\t\toff \t# use Newton\'s 3rd law\n')
        o.write('boundary\tp p p\t# periodic boundary conditions\n')
        o.write('atom_style\tfull\t# molecular + charge\n\n')

        o.write('#===========================================================\n')
        o.write('# DEFINE PAIR, BOND, AND ANGLE STYLES\n')
        o.write('#===========================================================\n')
        o.write('special_bonds   amber\n')
        if tip4p != None:
            o.write('pair_style      hybrid buck/coul/long 15.0 15.0 lj/cut/coul/long 15.0 15.0 {}\n'.format(tip4p))
        else:
            o.write('pair_style      hybrid buck/coul/long 15.0 15.0 lj/cut/coul/long 15.0 15.0\n')
        o.write('pair_modify     shift yes mix arithmetic       # using Lorenz-Berthelot mixing rules\n')
        o.write('bond_style      harmonic\n')
        o.write('angle_style     harmonic\n')
        o.write('dihedral_style  opls\n')
        if tip4p != None:
            o.write('kspace_style    pppm/tip4p 0.0001\n\n')
        else:
            o.write('kspace_style    {} 0.0001\n\n'.format(kspace.lower()))
        
        if flag_ecoh:
            o.write('# Compute cohesive energy\n')
            o.write('compute eng all pe/atom \n')
            o.write('compute eatoms all reduce sum c_eng\n\n')

        o.write('#===========================================================\n')
        o.write('# SETUP SIMULATIONS\n')
        o.write('#===========================================================\n\n')

        o.write('# READ IN COEFFICIENTS/COORDINATES/TOPOLOGY\n')
        o.write('if "${run} == 0" then &\n')
        o.write('   "read_data ${data_name}" &\n')
        o.write('else &\n')
        o.write('   "read_restart ${restart_name}"\n')
        o.write('include ${settings_name}\n\n')
        
        o.write('# SET RUN PARAMETERS\n')
        o.write('timestep\t1.0\t\t# fs\n')
        o.write('run_style\tverlet \t\t# Velocity-Verlet integrator\n')

        if neighbor_build == 1:
            o.write('neigh_modify every 1 delay 0 check yes one 10000\n')
        elif neighbor_build == 2:
            o.write('neigh_modify every 1 delay 0 check yes page 500000 one 50000\n')
        else:
            o.write('neigh_modify every 1 delay 10 check yes one 10000\n')
            
        o.write('\n# SET OUTPUTS\n')
        if flag_ecoh:
            o.write('thermo_style    custom step temp vol density etotal pe ebond eangle edihed ecoul elong evdwl enthalpy press c_eatoms\n')
        else:
            o.write('thermo_style    custom step temp vol density etotal pe ebond eangle edihed ecoul elong evdwl enthalpy press\n')
        o.write('thermo_modify   format float %14.6f\n')
        o.write('thermo ${thermo_freq}\n\n')

        o.write('# DECLARE RELEVANT OUTPUT VARIABLES\n')
        o.write('variable        my_step equal   step\n')
        o.write('variable        my_temp equal   temp\n')
        o.write('variable        my_rho  equal   density\n')
        o.write('variable        my_pe   equal   pe\n')
        o.write('variable        my_ebon equal   ebond\n')
        o.write('variable        my_eang equal   eangle\n')
        o.write('variable        my_edih equal   edihed\n')
        o.write('variable        my_evdw equal   evdwl\n')
        o.write('variable        my_eel  equal   (ecoul+elong)\n')
        o.write('variable        my_ent  equal   enthalpy\n')
        o.write('variable        my_P    equal   press\n')
        o.write('variable        my_vol  equal   vol\n\n')
        
        if flag_ecoh:
            o.write('variable \tnatoms \tequal "count(all)" \n')
            o.write('variable \tteng \tequal "c_eatoms"\n')
            o.write('variable \tecoh \tequal "v_teng/v_natoms"\n\n')
            o.write('fix averages all ave/time ${dump4avg} $(v_avg_freq/v_dump4avg) ${avg_freq} v_my_temp v_my_rho v_my_vol v_my_pe v_my_edih v_my_evdw v_my_eel v_my_ent v_my_P v_ecoh file ${run}.thermo.avg\n\n')
        else:
            o.write('fix averages all ave/time ${dump4avg} $(v_avg_freq/v_dump4avg) ${avg_freq} v_my_temp v_my_rho v_my_vol v_my_pe v_my_edih v_my_evdw v_my_eel v_my_ent v_my_P file ${run}.thermo.avg\n\n')

        if tether != None:
            o.write('# Set tether fix\n')
            o.write('group tethered_atoms id {}\n'.format(' '.join(tether[1:-1]) ))
            o.write('fix tether_atoms tethered_atoms spring/self {} {}\n'.format(tether[-1], tether[0]))
            o.write('\n')
        
        if tether_types != None:
            o.write('# Set tether fix for all atoms of types\n')
            o.write('group tethered_types type {}\n'.format(' '.join(tether_types[1:-1])))
            o.write('fix tether_types tethered_types spring/self {} {}\n'.format(tether_types[-1], tether_types[0]))
            o.write('\n')
            
        for i in range(nve_cycles):
            o.write('\n# CREATE COORDINATE DUMPS FOR NVE RELAXATION\n')
            o.write('dump relax all custom {} {}.nve.{}.lammpstrj id type x y z \n'.format('${coords_freq}', '${run}', str(i+1) ) )
            o.write('dump_modify relax sort  id\n\n')
            o.write('# INITIALIZE VELOCITIES AND CREATE THE CONSTRAINED RELAXATION FIX\n')
            o.write('if "${run} == 0" then &\n')
            o.write('"velocity        all create {} {} mom yes rot yes     # DRAW VELOCITIES" &\n'.format('${Temp}','${vseed'+ str(i+1) +'}'))
            o.write('"fix relax all nve/limit {}" &\n'.format(nve_dist))
            o.write('"run             10000" &\n')
            o.write('"unfix relax" &\n')
            o.write('"undump relax" \n\n')
            
        if fixes != None:
            o.write('# User-specified fixes\n')
            for fix in fixes:
                o.write('{}\n'.format(fix))
            o.write('\n')
            
        o.write('#===========================================================\n')
        o.write('# RUN PRODUCTION\n')
        o.write('#===========================================================\n\n')
        
        o.write('# UPDATE RUN PARAMETERS AND CREATE FIX\n')
        if flag_velocities:
            o.write('velocity        all create ${Temp} ${vseed} mom yes rot yes     # DRAW VELOCITIES\n')
        o.write('fix mom all momentum 1000 linear 1 1 1 angular # Zero out system linear and angular momentum every ps \n')
        
        o.write('\n# NPT equilibration, x and z direction to accomodate any lattice changes\n')
        axis_fixes = ''
        for axis in pressure_axis:
            axis_fixes += '{} {} {} 1000.0 '.format(axis, '${pressure}', '${pressure}')
        o.write('fix equil all npt temp {} {} 100.0 {} # NPT, nose-hoover 100 fs T relaxation\n'.format('${Temp}', '${Temp}', axis_fixes))
        o.write('dump equil all custom ${coords_freq} ${run}.npt.lammpstrj id type x y z \n')
        o.write('dump_modify equil sort  id\n\n')

        o.write('# RUN NPT\n')
        o.write('run\t\t${nSteps_NPT}\n')
        o.write('unfix equil\n')
        o.write('undump equil\n\n')
        
        o.write('\n# NVT run\n')
        o.write('fix equil all nvt temp ${Temp} ${Temp} 100.0 # NVT, nose-hoover 100 fs T relaxation\n\n')

        o.write('# CREATE COORDINATE DUMPS FOR EQUILIBRIUM\n')
        o.write('dump equil all custom ${coords_freq} ${run}.nvt.lammpstrj id type x y z \n')
        o.write('dump_modify equil sort  id\n\n')

        o.write('# RUN NVT\n')
        o.write('run\t\t${nSteps_NVT}\n')
        o.write('unfix equil\n')
        o.write('undump equil\n\n')

        o.write('# WRITE RESTART FILES, CLEANUP, AND EXIT\n')
        o.write('write_restart   extend.end.restart\n')
        o.write('write_data      extend.end.data pair ii\n')
        o.write('unfix           averages\n')
        if tether != None: o.write('unfix           tether_atoms\n')
        if tether_types != None: o.write('unfix           tether_types\n\n')
        
        if fixes != None:
            for fix in fixes:
                fix = fix.split()
                o.write('unfix           {}\n'.format(fix[1]))
            o.write('\n')
        
        o.write('\n# Update run number\n')
        o.write('variable sub equal (v_run+1)\n')
        o.write('shell sed -i /variable.*run.*index/s/{}/{}/g {}\n'.format('${run}', '${sub}', output))
        o.write('shell echo "Run ${run} finished." >> ${run}.success\n')
        
        if extension_number > 0:
            if submission_manager.upper() == 'PBS':
                o.write("if '{} < {}' then 'shell qsub {}'\n".format('${run}', extension_number, submit_file))
            elif submission_manager.upper() == 'SLURM':
                o.write("if '{} < {}' then 'shell sbatch {}'\n".format('${run}', extension_number, submit_file))
            
        if commands != None:
            o.write('\n# User-specified shell commands\n')
            for cmd in commands:
                o.write('{}\n'.format(cmd))
            o.write('\n')

    print('File written to {}.'.format(output))
    print('Success!')
    
    return True
