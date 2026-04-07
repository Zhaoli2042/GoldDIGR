# ── SNIPPET: ops_status_dashboard/dft_jobs_tree_cli_table_with_stage_barriers ─
# Scheduler:   any
# Tool:        any
# Tested:      {{PLUGIN_NAME}}
# Notes: This is the full tested script body.
# ────────────────────────────────────────────────────────────

#!/usr/bin/env python3
"""
check_status.py - Check status of all DFT verification jobs
"""

import os
import json
import sys
from pathlib import Path

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


def format_status(status_dict, stage):
    """Format status for a stage."""
    if status_dict is None:
        return "not_found"
    
    stage_data = status_dict.get(stage, {})
    status = stage_data.get('status', 'not_run')
    
    return status


def format_energy(status_dict, key):
    """Format energy value."""
    irc_data = status_dict.get('dft_irc', {})
    value = irc_data.get(key)
    
    if value is None:
        return "N/A"
    
    return f"{value:.2f}"


def main():
    # Find pipeline directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    jobs_dir = os.path.join(script_dir, "jobs")
    
    if not os.path.exists(jobs_dir):
        print(f"ERROR: Jobs directory not found: {jobs_dir}")
        sys.exit(1)
    
    # Get job list
    job_list_file = os.path.join(script_dir, "job_list.txt")
    if os.path.exists(job_list_file):
        with open(job_list_file, 'r') as f:
            job_names = [line.strip() for line in f if line.strip()]
    else:
        job_names = sorted(os.listdir(jobs_dir))
    
    # Print header
    print("=" * 120)
    print(f"{'Job Name':<40} {'COPT':<12} {'TSOPT':<12} {'IRC':<12} {'Fwd ΔG‡':<10} {'Rev ΔG‡':<10} {'ΔG_rxn':<10}")
    print("=" * 120)
    
    # Summary counters
    total = 0
    completed = 0
    failed = 0
    running = 0
    
    for job_name in job_names:
        job_dir = os.path.join(jobs_dir, job_name)
        if not os.path.isdir(job_dir):
            continue
        
        total += 1
        status = load_status(job_dir)
        
        if status is None:
            copt = tsopt = irc = "not_started"
            fwd = rev = rxn = "N/A"
            running += 1
        else:
            copt = format_status(status, 'dft_copt')
            tsopt = format_status(status, 'dft_tsopt')
            irc = format_status(status, 'dft_irc')
            
            fwd = format_energy(status, 'forward_barrier_kcal')
            rev = format_energy(status, 'reverse_barrier_kcal')
            rxn = format_energy(status, 'reaction_energy_kcal')
            
            if irc == 'success':
                completed += 1
            elif irc in ['not_run', 'not_started']:
                if copt in ['not_run', 'not_started']:
                    running += 1
                else:
                    failed += 1
            else:
                failed += 1
        
        # Color coding (ANSI)
        def colorize(s, status):
            if status == 'success':
                return f"\033[92m{s}\033[0m"  # Green
            elif status in ['not_started', 'not_run']:
                return f"\033[90m{s}\033[0m"  # Gray
            else:
                return f"\033[91m{s}\033[0m"  # Red
        
        print(f"{job_name:<40} {colorize(copt, copt):<21} {colorize(tsopt, tsopt):<21} {colorize(irc, irc):<21} {fwd:<10} {rev:<10} {rxn:<10}")
    
    print("=" * 120)
    print(f"\nSummary: {completed}/{total} completed, {failed} failed, {running} pending/running")
    
    # Detailed failures
    if failed > 0:
        print("\nFailed jobs:")
        for job_name in job_names:
            job_dir = os.path.join(jobs_dir, job_name)
            status = load_status(job_dir)
            if status:
                irc = format_status(status, 'dft_irc')
                if irc not in ['success', 'not_run', 'not_started']:
                    reason = status.get('dft_irc', {}).get('fail_reason', 'unknown')
                    print(f"  {job_name}: {irc} - {reason}")


if __name__ == "__main__":
    main()
