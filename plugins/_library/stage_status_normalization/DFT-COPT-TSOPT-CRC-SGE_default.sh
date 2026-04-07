# ── SNIPPET: stage_status_normalization/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Missing stage dict => not_run/not_started semantics rather than crashing.
# Notes: Keeps reporting stable across schema drift.
# ────────────────────────────────────────────────────────────

def format_status(status_dict, stage):
    """Format status for a stage."""
    if status_dict is None:
        return "not_found"

    stage_data = status_dict.get(stage, {})
    status = stage_data.get('status', 'not_run')

    return status
