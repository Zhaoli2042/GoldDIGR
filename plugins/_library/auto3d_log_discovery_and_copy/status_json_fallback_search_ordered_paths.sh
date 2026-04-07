# ── SNIPPET: auto3d_log_discovery_and_copy/status_json_fallback_search_ordered_paths ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Notes: Used by CLI dashboards and health monitors.
# ────────────────────────────────────────────────────────────

import os, json

def load_status(job_dir):
    """Load workflow status from job directory."""
    status_files = [
        os.path.join(job_dir, "final_status.json"),
        os.path.join(job_dir, "output", "workflow_status.json"),
    ]

    for sf in status_files:
        if os.path.exists(sf):
            with open(sf, 'r') as f:
                return json.load(f)

    return None
