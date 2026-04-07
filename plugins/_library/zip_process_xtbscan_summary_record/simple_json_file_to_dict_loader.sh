# ── SNIPPET: zip_process_xtbscan_summary_record/simple_json_file_to_dict_loader ─
# Scheduler:   any
# Tool:        any
# Tested:      get_auto3d_calc_status
# Notes: Used for benchmark JSON ingestion.
# ────────────────────────────────────────────────────────────

import json
from typing import Dict, Any

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)
