# ── SNIPPET: status_json_manifest/slurm_runtime_metadata_snapshot ─
# Scheduler:   slurm
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: Producer-side block; intended to be written into per-batch benchmark JSON.
# ────────────────────────────────────────────────────────────

import os
import socket

def capture_slurm_metadata():
    hostname = socket.gethostname()
    slrmp = os.environ.get("SLURM_JOB_PARTITION", "")
    slrmid = os.environ.get("SLURM_JOB_ID", "")
    slrmjname = os.environ.get("SLURM_JOB_NAME", "")
    slrmnodes = os.environ.get("SLURM_JOB_NODELIST", "")
    return {
        "hostname": hostname,
        "slurm": {
            "partition": slrmp,
            "job_id": slrmid,
            "job_name": slrmjname,
            "nodelist": slrmnodes,
        },
    }
