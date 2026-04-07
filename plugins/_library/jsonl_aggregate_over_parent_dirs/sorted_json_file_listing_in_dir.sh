# ── SNIPPET: jsonl_aggregate_over_parent_dirs/sorted_json_file_listing_in_dir ─
# Scheduler:   any
# Tool:        any
# Tested:      get_auto3d_calc_status
# Notes: Consumer-side block for status aggregation.
# ────────────────────────────────────────────────────────────

import os
from typing import List

def list_bench_json_files() -> List[str]:
    if not os.path.exists(BENCH_DIR):
        return []
    return sorted(
        os.path.join(BENCH_DIR, f)
        for f in os.listdir(BENCH_DIR)
        if f.endswith(".json")
    )
