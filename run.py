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
import logging
import sys
from pathlib import Path


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]
    # Try container path first, fall back to local
    for log_path in [Path("/app/data/db/pipeline.log"), Path("data/db/pipeline.log")]:
        if log_path.parent.exists():
            handlers.append(logging.FileHandler(str(log_path), mode="a"))
            break
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="golddigr — SI Mining Pipeline")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--start", type=int, default=0, help="Start index in CSV")
    parser.add_argument("--end", type=int, default=None, help="End index in CSV")
    parser.add_argument("--batch", type=int, default=50, help="Batch size per stage")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("--retry-failed", action="store_true", help="Re-queue FAILED jobs")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

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
