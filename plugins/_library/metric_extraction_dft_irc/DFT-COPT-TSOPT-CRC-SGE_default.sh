# ── SNIPPET: metric_extraction_dft_irc/DFT-COPT-TSOPT-CRC-SGE_default ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Read metrics only from status_dict['dft_irc'] to match pipeline contract.
#   - Missing metric => 'N/A' (string) for table printing.
# Notes: Keys used: forward_barrier_kcal, reverse_barrier_kcal, reaction_energy_kcal.
# ────────────────────────────────────────────────────────────

def format_energy(status_dict, key):
    """Format energy value."""
    irc_data = status_dict.get('dft_irc', {})
    value = irc_data.get(key)

    if value is None:
        return "N/A"

    return f"{value:.2f}"
