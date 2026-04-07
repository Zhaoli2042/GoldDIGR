#!/usr/bin/env python3
"""
run.py – Entry point for the golddigr pipeline.

Usage:
    python run.py                          # process all articles
    python run.py --start 0 --end 100      # process a range
    python run.py --status                 # show pipeline progress
    python run.py --retry-failed           # re-queue failed jobs
"""

import argparse
import sys
from pathlib import Path

from pipeline import setup_logging

_QUIET_LOGGERS = [
    "selenium", "urllib3", "httpx", "transformers", "torch", "accelerate",
]


def main():
    # If "plugin" is the first arg, redirect to plugin.py (runs on host, no container)
    if len(sys.argv) > 1 and sys.argv[1] == "plugin":
        import importlib.util
        plugin_script = Path(__file__).parent / "plugin.py"
        if plugin_script.exists():
            sys.argv = [str(plugin_script)] + sys.argv[2:]
            spec = importlib.util.spec_from_file_location("plugin", plugin_script)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.main()
            return
        else:
            print("Error: plugin.py not found. Plugin commands require plugin.py.")
            sys.exit(1)

    parser = argparse.ArgumentParser(description="golddigr — SI Mining Pipeline")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--start", type=int, default=0, help="Start index in CSV")
    parser.add_argument("--end", type=int, default=None, help="End index in CSV")
    parser.add_argument("--batch", type=int, default=50, help="Batch size per stage")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("--retry-failed", action="store_true", help="Re-queue FAILED jobs")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()
    setup_logging(args.verbose, log_filename="pipeline.log", quiet_loggers=_QUIET_LOGGERS)

    if args.status:
        _show_status(args.config)
        return

    if args.retry_failed:
        _retry_failed(args.config)
        return

    from pipeline.orchestrator import Pipeline
    pipeline = Pipeline(args.config)
    pipeline.run(start=args.start, end=args.end, batch_size=args.batch)


def _show_status(config_path: str) -> None:
    from pipeline.orchestrator import PipelineConfig
    from pipeline.job_db import JobDB
    cfg = PipelineConfig(config_path)
    db = JobDB(cfg["paths"]["db_path"])
    summary = db.summary()
    total = sum(summary.values())

    print("\n╔══════════════════════════════════════╗")
    print("║       Gold Pipeline Status           ║")
    print("╠══════════════════════════════════════╣")
    for status, count in sorted(summary.items()):
        bar = "█" * int(40 * count / max(total, 1))
        print(f"║ {status:<20s} {count:>5d} {bar}")
    print(f"╠══════════════════════════════════════╣")
    print(f"║ {'TOTAL':<20s} {total:>5d}              ║")
    print("╚══════════════════════════════════════╝\n")
    db.close()


def _retry_failed(config_path: str) -> None:
    from pipeline.orchestrator import PipelineConfig
    from pipeline.job_db import JobDB, JobStatus
    cfg = PipelineConfig(config_path)
    db = JobDB(cfg["paths"]["db_path"])
    failed = db.get_jobs(JobStatus.FAILED)
    for job in failed:
        db.advance(job["id"], JobStatus.PENDING, error=None)
    print(f"Re-queued {len(failed)} failed jobs → PENDING")
    db.close()


if __name__ == "__main__":
    main()
