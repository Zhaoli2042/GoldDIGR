# ── SNIPPET: htcondor_submit_file_transfer_and_remap/DFT-singlepoint-OSG-Condor_default ─
# Scheduler:   htcondor
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Invariants:
#   - Job must always produce results.tar.gz; HTCondor remaps it using zip_relpath.
#   - Queue input list must be two columns: zip_abspath, zip_relpath (comma+space separated in this workflow).
#   - transfer_input_files must include both the executable script and the per-job zip.
# Notes: In original plugin, +SingularityImage is hardcoded; to make start.sh token replacement effective, use __CONTAINER_IMAGE__.
# ────────────────────────────────────────────────────────────

# file: batch_job.submit

# --- Container ---
+SingularityImage = "__CONTAINER_IMAGE__"

# --- Job Execution ---
executable = run_orca_wbo.sh
arguments = $(zip_abspath)

# --- Input Transfer ---
transfer_input_files = run_orca_wbo.sh, $(zip_abspath)

# --- Output Transfer ---
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_output_files = results.tar.gz

# Remap output to nested directory structure under results/
transfer_output_remaps = "results.tar.gz = __RESULTS_DIR__/$(zip_relpath)_results.tar.gz"

# --- Resources ---
requirements = (Microarch >= "x86_64-v3")
request_cpus = {{REQUEST_CPUS}}
request_memory = {{REQUEST_MEMORY}}
request_disk = {{REQUEST_DISK}}

# --- Logging ---
output = logs/$(Cluster)_$(Process).out
error = logs/$(Cluster)_$(Process).err
log = logs/$(Cluster)_$(Process).log

# --- Queue ---
queue zip_abspath, zip_relpath from $(input_list)
