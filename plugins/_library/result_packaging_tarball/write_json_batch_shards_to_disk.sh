# ── SNIPPET: result_packaging_tarball/write_json_batch_shards_to_disk ─
# Scheduler:   any
# Tool:        any
# Tested:      purdue_standby_auto3d_auto_batch
# Notes: File-based glue between batching and submission.
# ────────────────────────────────────────────────────────────

import json
import os
from typing import Dict, List

def write_batch_dict_files(batch_dicts: List[Dict[str, str]]) -> None:
    ensure_dir(BATCH_DICTS_PATH)
    for i, batch_dict in enumerate(batch_dicts):
        out_path = os.path.join(BATCH_DICTS_PATH, f"batch_{i}.json")
        with open(out_path, "w") as f:
            json.dump(batch_dict, f)
