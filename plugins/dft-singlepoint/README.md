# DFT single point calculation

For each XYZ file:
1. run DFT single point energy calculation with ORCA
2. Calculate Wiberg Bond Order (WBO) with ORCA's result using Multiwfn

The process will be running on a cluster with HTCondor
The software (ORCA and Multiwfn) are going to be provided via a container

This folder contains a lot of scripts:
1. start.sh: a main script for starting the processes. It takes in a tar.gz file composed of individual .zip files, each .zip file contains one or several XYZ files
1.1 monitor_submit.sh: a submission script for submitting jobs to HTCondor
1.2 monitor_health.sh: a script for healing jobs that exceed CPU/memory limit the job requested
1.3 backup_results.sh: a script for backing up generated results to a group storage folder on Open-Science Grid
2. run_orca_wbo.sh: script for running ORCA and Multiwfn. This is the main "driver" script
3. batch_job.submit: HTCondor submission script. 
4. add_data.sh: when the processes starts, this script will add more input data to the queue for the submission script to pick up.
