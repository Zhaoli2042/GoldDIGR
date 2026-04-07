# ── SNIPPET: htcondor_submit_file_transfer_and_remap/apptainer_wrapper_executable_with_bind_mount_workdir ─
# Scheduler:   htcondor
# Tool:        apptainer
# Tested:      golddigr
# Notes: run_wrapper.sh as-is with placeholders.
# ────────────────────────────────────────────────────────────

#!/bin/bash

if [ -r /opt/crc/Modules/current/init/bash ]; then
    source /opt/crc/Modules/current/init/bash
fi

CONTAINER_IMAGE="{{CONTAINER_IMAGE}}"
ZIP_ABS_PATH=$1
COMPUTE_SCRIPT="{{COMPUTE_SCRIPT:-run_orca_wbo.sh}}"

/usr/bin/apptainer exec --bind $PWD:$PWD "$CONTAINER_IMAGE" /bin/bash "$COMPUTE_SCRIPT" "$ZIP_ABS_PATH"
