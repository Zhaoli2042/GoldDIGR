# ── SNIPPET: htcondor_submit_file_transfer_and_remap/queue_from_two_column_csv_and_remap_results_to_nested_tree ─
# Scheduler:   htcondor
# Tool:        any
# Tested:      golddigr
# Notes: This is the tested file content with placeholders added for reuse.
# ────────────────────────────────────────────────────────────

# file: batch_job.submit

executable = {{SUBMIT_EXECUTABLE:-run_wrapper.sh}}
arguments = $(zip_abspath)

transfer_input_files = run_orca_wbo.sh, run_wrapper.sh, $(zip_abspath)

should_transfer_files = YES
when_to_transfer_output = ON_EXIT

transfer_output_files = results.tar.gz

transfer_output_remaps = "results.tar.gz = {{RESULTS_DIR_ABS}}/$(zip_relpath)_results.tar.gz"

requirements = (Machine != "")
request_cpus = {{REQUEST_CPUS:-4}}
request_memory = {{REQUEST_MEMORY:-4 GB}}
request_disk = {{REQUEST_DISK:-20 GB}}

output = logs/$(Cluster)_$(Process).out
error  = logs/$(Cluster)_$(Process).err
log    = logs/$(Cluster)_$(Process).log

queue zip_abspath, zip_relpath from $(input_list)
