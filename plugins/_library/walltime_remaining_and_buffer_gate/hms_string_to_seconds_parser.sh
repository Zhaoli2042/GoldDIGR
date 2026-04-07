# ── SNIPPET: walltime_remaining_and_buffer_gate/hms_string_to_seconds_parser ─
# Scheduler:   any
# Tool:        any
# Tested:      get_auto3d_calc_status
# Notes: Used to aggregate elapsed time across batches.
# ────────────────────────────────────────────────────────────

def parse_hms_to_seconds(hms: str) -> int:
    if not hms:
        return 0
    parts = hms.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + int(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + int(s)
        else:
            return 0
    except ValueError:
        return 0
