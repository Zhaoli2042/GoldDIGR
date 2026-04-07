# ── SNIPPET: walltime_remaining_and_buffer_gate/seconds_to_hms_formatter ─
# Scheduler:   any
# Tool:        any
# Tested:      get_auto3d_calc_status
# Notes: Used for reporting total and per-molecule average time.
# ────────────────────────────────────────────────────────────

def seconds_to_hms(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"
