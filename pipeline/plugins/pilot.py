"""
pipeline.plugins.pilot – Submit pilot jobs and watch for completion.

The pilot:
  1. Picks N representative XYZ files from the article data
  2. Creates a mini-package with just those files
  3. Runs the glue script
  4. Watches for job completion (polls scheduler or checks output files)
  5. Collects logs and results for diagnosis

Works with any scheduler — detects HTCondor/SLURM/SGE from plugin.yaml
or by probing which commands are available.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess


def _get_project_root() -> "Path":
    """Return project root, works inside container (/app) and on host."""
    from pathlib import Path
    if Path("/app/run.py").exists():
        return Path("/app")
    p = Path(__file__).resolve().parent
    for _ in range(5):
        if (p / "plugin.py").exists() or (p / "run.py").exists() or (p / "data").exists():
            return p
        p = p.parent
    return Path.cwd()
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .registry import load_manifest

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Scheduler detection and polling
# ═══════════════════════════════════════════════════════════════════════

def _detect_scheduler() -> str:
    """Detect which scheduler is available on this system."""
    for cmd, name in [("condor_q", "htcondor"), ("squeue", "slurm"), ("qstat", "sge")]:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
            return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "local"


def _count_running_jobs(scheduler: str, job_prefix: str = "golddigr-pilot") -> int:
    """Count how many pilot jobs are still running/idle/held."""
    try:
        if scheduler == "htcondor":
            result = subprocess.run(
                ["condor_q", "-nobatch", "-constraint",
                 f'JobBatchName == "{job_prefix}"', "-totals"],
                capture_output=True, text=True, timeout=30,
            )
            # Parse "X jobs; X completed, X removed, X idle, X running, X held"
            for line in result.stdout.splitlines():
                if "jobs;" in line:
                    parts = line.split(";")[0].strip().split()
                    total = int(parts[0])
                    # Count completed
                    completed = 0
                    for segment in line.split(","):
                        if "completed" in segment:
                            completed = int(segment.strip().split()[0])
                    return total - completed
            return 0

        elif scheduler == "slurm":
            result = subprocess.run(
                ["squeue", "-u", os.environ.get("USER", ""), "--noheader",
                 "-o", "%j", "--name", job_prefix],
                capture_output=True, text=True, timeout=30,
            )
            return len([l for l in result.stdout.strip().splitlines() if l.strip()])

        elif scheduler == "sge":
            result = subprocess.run(
                ["qstat", "-u", os.environ.get("USER", "")],
                capture_output=True, text=True, timeout=30,
            )
            return len([l for l in result.stdout.strip().splitlines()
                        if job_prefix in l])

    except Exception as e:
        logger.warning("Failed to poll scheduler: %s", e)

    return 0


def _get_held_jobs(scheduler: str, job_prefix: str = "golddigr-pilot") -> List[Dict]:
    """Get details about held/failed jobs."""
    held = []
    try:
        if scheduler == "htcondor":
            result = subprocess.run(
                ["condor_q", "-constraint",
                 f'JobBatchName == "{job_prefix}" && JobStatus == 5',
                 "-af", "ClusterId", "ProcId", "HoldReason"],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    held.append({"id": f"{parts[0]}.{parts[1]}", "reason": parts[2]})

        elif scheduler == "slurm":
            result = subprocess.run(
                ["squeue", "-u", os.environ.get("USER", ""), "--noheader",
                 "-o", "%i %j %T %r", "--name", job_prefix],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 4 and parts[2] in ("FAILED", "TIMEOUT", "NODE_FAIL"):
                    held.append({"id": parts[0], "reason": parts[3]})

    except Exception as e:
        logger.warning("Failed to get held jobs: %s", e)
    return held


# ═══════════════════════════════════════════════════════════════════════
# File selection
# ═══════════════════════════════════════════════════════════════════════

def _pick_representative_files(xyz_dir: Path, n: int = 3) -> List[Path]:
    """
    Pick N representative XYZ files — first, middle, last.
    This gives diversity: small molecules, medium, large/complex.
    """
    all_xyz = sorted(xyz_dir.rglob("*.xyz"))
    if not all_xyz:
        return []
    if len(all_xyz) <= n:
        return all_xyz

    indices = [0]
    if n >= 3:
        indices.append(len(all_xyz) // 2)
    if n >= 2:
        indices.append(len(all_xyz) - 1)
    # Fill remaining slots evenly
    while len(indices) < n:
        step = len(all_xyz) // (n + 1)
        for i in range(1, n + 1):
            idx = i * step
            if idx not in indices and idx < len(all_xyz):
                indices.append(idx)
            if len(indices) >= n:
                break

    return [all_xyz[i] for i in sorted(set(indices))[:n]]


# ═══════════════════════════════════════════════════════════════════════
# Result collection
# ═══════════════════════════════════════════════════════════════════════

def _collect_results(workdir: Path) -> Dict[str, Any]:
    """
    Scan the pilot working directory for results, logs, and errors.
    Unpacks result tarballs and zips into temp dirs to read contents.
    Returns a structured dict suitable for LLM diagnosis.
    """
    import tarfile
    import tempfile
    import zipfile

    results: Dict[str, Any] = {
        "jobs": [],
        "summary": {"total": 0, "passed": 0, "failed": 0, "unknown": 0},
    }

    # Look for result files — be flexible about structure
    results_dir = workdir / "results"
    logs_dir = workdir / "logs"

    # Find all job output directories/files
    job_outputs = []

    if results_dir.is_dir():
        for f in sorted(results_dir.rglob("*_results.tar.gz")):
            job_outputs.append(("result_tarball", f))
        for f in sorted(results_dir.rglob("*.out")):
            job_outputs.append(("stdout", f))

    # Also check for SLURM-style output
    for f in sorted(workdir.glob("*.out")):
        job_outputs.append(("stdout", f))
    for f in sorted(workdir.glob("*.err")):
        job_outputs.append(("stderr", f))
    # Root-level .log files (workspace snapshot layout)
    for f in sorted(workdir.glob("*.log")):
        if f.is_file():
            job_outputs.append(("log", f))

    if logs_dir.is_dir():
        for f in sorted(logs_dir.rglob("*.out")):
            job_outputs.append(("log", f))
        for f in sorted(logs_dir.rglob("*.err")):
            job_outputs.append(("log_err", f))
        # SGE-style logs: name.o.jobid.taskid, name.e.jobid.taskid
        for f in sorted(logs_dir.rglob("*.o.*")):
            if f.is_file():
                job_outputs.append(("log", f))
        for f in sorted(logs_dir.rglob("*.e.*")):
            if f.is_file():
                job_outputs.append(("log_err", f))
        # General .log files (launch errors, monitor logs, etc.)
        for f in sorted(logs_dir.rglob("*.log")):
            if f.is_file():
                job_outputs.append(("log", f))

    # Scan work/ subdirectories for SGE output files
    # (workspace isolation snapshots SGE outputs into work/)
    work_dir = workdir / "work"
    if work_dir.is_dir():
        for f in sorted(work_dir.rglob("*.o[0-9]*")):
            if f.is_file():
                job_outputs.append(("log", f))
        for f in sorted(work_dir.rglob("*.e[0-9]*")):
            if f.is_file():
                job_outputs.append(("log_err", f))
        for f in sorted(work_dir.rglob("*.out")):
            if f.is_file():
                job_outputs.append(("log", f))
        for f in sorted(work_dir.rglob("*.log")):
            if f.is_file():
                job_outputs.append(("log", f))

    # Look for status.json files (written by run_orca_wbo.sh etc.)
    for f in sorted(workdir.rglob("status.json")):
        try:
            json.loads(f.read_text())
            job_outputs.append(("status_json", f))
        except Exception:
            pass

    # ── Unpack result tarballs/zips to read contents ──────────────────
    # We unpack to a temp dir, read what we need, temp dir auto-cleans.
    # NEVER unpack in-place to avoid clobbering existing files.
    _extracted_outputs: List[Tuple[str, str, str]] = []  # (job_name, file_type, content)

    for otype, fpath in list(job_outputs):
        if otype != "result_tarball":
            continue

        # Derive job name from tarball path
        job_stem = fpath.stem.replace("_results.tar", "").replace("_results", "")
        job_stem = job_stem.split(".")[0]

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)

                # Unpack tarball
                if fpath.name.endswith(".tar.gz") or fpath.name.endswith(".tgz"):
                    with tarfile.open(fpath, "r:gz") as tf:
                        # Safety: only extract regular files, skip anything suspicious
                        safe_members = [
                            m for m in tf.getmembers()
                            if m.isfile()
                            and not m.name.startswith("/")
                            and ".." not in m.name
                        ]
                        tf.extractall(tmpdir, members=safe_members)

                # Now scan the temp dir for interesting files
                for inner in tmpdir_path.rglob("*"):
                    if not inner.is_file():
                        continue

                    # Read status.json
                    if inner.name == "status.json":
                        content = inner.read_text(errors="ignore")[:5000]
                        _extracted_outputs.append((job_stem, "packed_status_json", content))

                    # Read ORCA output files
                    elif inner.suffix == ".out" and inner.stat().st_size < 500_000:
                        content = inner.read_text(errors="ignore")[:5000]
                        _extracted_outputs.append((job_stem, f"packed_orca_out:{inner.name}", content))

                    # Read log files
                    elif inner.name.endswith("_log.out"):
                        content = inner.read_text(errors="ignore")[:3000]
                        _extracted_outputs.append((job_stem, f"packed_log:{inner.name}", content))

                    # Read .inp files (ORCA input — useful for debugging wrong keywords)
                    elif inner.suffix == ".inp" and inner.stat().st_size < 50_000:
                        content = inner.read_text(errors="ignore")[:3000]
                        _extracted_outputs.append((job_stem, f"packed_inp:{inner.name}", content))

                    # Also check inside any zip files in the tarball
                    elif inner.suffix == ".zip":
                        try:
                            with zipfile.ZipFile(inner) as zf:
                                for zname in zf.namelist():
                                    if zname.endswith((".out", ".json", ".inp", "_log.out")):
                                        zdata = zf.read(zname).decode("utf-8", errors="ignore")[:3000]
                                        _extracted_outputs.append((job_stem, f"packed_zip:{zname}", zdata))
                        except Exception:
                            pass

        except Exception as e:
            logger.debug("Failed to unpack %s: %s", fpath, e)

    # Compile per-job information
    # First pass: group all outputs by job name
    job_files: Dict[str, List] = {}
    for output_type, filepath in job_outputs:
        # Normalize job name from various file patterns
        name = filepath.stem
        for suffix in ("_results", ".tar"):
            name = name.replace(suffix, "")
        # SGE logs: orca_wbo_job_1.o.364862.1 → orca_wbo_job_1
        name = name.split(".")[0]

        if name not in job_files:
            job_files[name] = []
        job_files[name].append((output_type, filepath))

    # Second pass: also group extracted-from-tarball outputs by job name
    extracted_by_job: Dict[str, List[Tuple[str, str]]] = {}
    for job_stem, ftype, content in _extracted_outputs:
        if job_stem not in extracted_by_job:
            extracted_by_job[job_stem] = []
        extracted_by_job[job_stem].append((ftype, content))
        # Ensure the job appears in job_files even if only tarball content exists
        if job_stem not in job_files:
            job_files[job_stem] = []

    for job_name, file_list in sorted(job_files.items()):
        job_info: Dict[str, Any] = {
            "name": job_name,
            "files": {},
            "status": "unknown",
            "errors": [],
            "has_result_tarball": False,
        }

        _ERROR_KEYWORDS = (
            "error", "fatal", "abort", "failed", "killed",
            "no such file", "not found", "convergence",
            "exceeded", "timeout", "orca failed",
            "segmentation fault", "bus error", "core dumped",
        )

        # Read all log content for this job (from files on disk)
        for otype, fpath in file_list:
            try:
                content = fpath.read_text(errors="ignore")[:5000]
                job_info["files"][otype] = {
                    "path": str(fpath.relative_to(workdir)),
                    "content": content,
                }

                if otype == "result_tarball":
                    job_info["has_result_tarball"] = True

                content_lower = content.lower()
                if any(kw in content_lower for kw in _ERROR_KEYWORDS):
                    for line in content.splitlines():
                        ll = line.lower()
                        if any(kw in ll for kw in _ERROR_KEYWORDS):
                            job_info["errors"].append(line.strip())

                # Parse status.json if present
                if otype == "status_json":
                    try:
                        sdata = json.loads(content)
                        molecules = sdata.get("molecules", {})
                        if molecules:
                            completed = sum(1 for m in molecules.values()
                                            if m.get("status") == "complete")
                            total = len(molecules)
                            if completed == 0:
                                job_info["errors"].append(
                                    f"status.json: 0/{total} molecules completed"
                                )
                    except Exception:
                        pass

            except Exception:
                pass

        # Also include content extracted from inside tarballs/zips
        for ftype, content in extracted_by_job.get(job_name, []):
            job_info["files"][ftype] = {
                "path": f"(inside results.tar.gz)",
                "content": content,
            }

            content_lower = content.lower()
            if any(kw in content_lower for kw in _ERROR_KEYWORDS):
                for line in content.splitlines():
                    ll = line.lower()
                    if any(kw in ll for kw in _ERROR_KEYWORDS):
                        job_info["errors"].append(line.strip())

            # Parse packed status.json
            if ftype == "packed_status_json":
                try:
                    sdata = json.loads(content)
                    molecules = sdata.get("molecules", {})
                    if molecules:
                        completed = sum(1 for m in molecules.values()
                                        if m.get("status") == "complete")
                        total = len(molecules)
                        if completed == 0:
                            job_info["errors"].append(
                                f"status.json (packed): 0/{total} molecules completed"
                            )
                        elif completed < total:
                            partial = total - completed
                            job_info["errors"].append(
                                f"status.json (packed): {completed}/{total} complete, "
                                f"{partial} incomplete"
                            )
                except Exception:
                    pass

        # Determine status: errors ALWAYS override tarball presence
        if job_info["errors"]:
            job_info["status"] = "failed"
        elif job_info["has_result_tarball"]:
            job_info["status"] = "passed"

        del job_info["has_result_tarball"]
        results["jobs"].append(job_info)

    # Summary
    results["summary"]["total"] = len(results["jobs"])
    for job in results["jobs"]:
        if job["status"] == "passed":
            results["summary"]["passed"] += 1
        elif job["status"] == "failed":
            results["summary"]["failed"] += 1
        else:
            results["summary"]["unknown"] += 1

    return results


# ═══════════════════════════════════════════════════════════════════════
# Main pilot runner
# ═══════════════════════════════════════════════════════════════════════

def run_pilot(
    plugin_dir: Path,
    xyz_root: Path,
    *,
    n_jobs: int = 3,
    poll_interval: int = 60,
    max_wait: int = 7200,      # 2 hours max
    auto_diagnose: bool = False,
    prep_only: bool = False,
    resume_dir: Optional[Path] = None,
    provider: str = "openai",
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Run a pilot test of a plugin's workflow.

    Three modes:
      - Full (default): prep → launch → watch → collect
      - Prep-only (--prep-only): prep only, user launches manually on host
      - Resume (--pilot-dir): skip prep, watch existing pilot → collect

    Returns a dict with pilot results, suitable for diagnose().
    """
    plugin_dir = Path(plugin_dir).resolve()
    manifest = load_manifest(plugin_dir)
    plugin_name = manifest.get("name", "unknown")
    scheduler = manifest.get("scheduler", _detect_scheduler())

    # ── Resume mode: skip prep, go straight to watch/collect ──────────
    if resume_dir is not None:
        pilot_dir = Path(resume_dir).resolve()
        if not pilot_dir.is_dir():
            print(f"❌ Pilot directory not found: {pilot_dir}")
            return {"error": "pilot_dir_not_found"}

        print(f"\n🔄 Resuming pilot: {pilot_dir.name}")

        # Load pilot config
        config_path = pilot_dir / "pilot_config.json"
        if config_path.exists():
            pilot_config = json.loads(config_path.read_text())
        else:
            pilot_config = {"plugin": plugin_name, "scheduler": scheduler}

        start_time = time.time()
        # Jump to watch phase
        return _watch_and_collect(
            pilot_dir, pilot_config, scheduler,
            poll_interval, max_wait, auto_diagnose,
            provider, model, start_time, manifest,
        )

    # ── Prep phase (shared by full and prep-only modes) ───────────────

    # Soft cap on pilot jobs — this is a TEST, not a production run
    _PILOT_SOFT_CAP = 5
    _PILOT_HARD_CAP = 10
    if n_jobs > _PILOT_HARD_CAP:
        print(f"⚠  Pilot is for testing, not production. Max {_PILOT_HARD_CAP} jobs.")
        print(f"   Use 'plugin launch' for full runs.")
        n_jobs = _PILOT_HARD_CAP
    elif n_jobs > _PILOT_SOFT_CAP:
        print(f"⚠  {n_jobs} pilot jobs is more than typical (1-3 recommended).")
        print(f"   Proceeding anyway.\n")

    print(f"\n🧪 Pilot test: {plugin_name}")
    print(f"   Scheduler: {scheduler}")
    print(f"   Jobs: {n_jobs}")
    if prep_only:
        print(f"   Mode: prep-only (launch manually on host)")
    print()

    # Pick representative files
    xyz_files = _pick_representative_files(xyz_root, n_jobs)
    if not xyz_files:
        # Fallback: check for sample files in the plugin directory
        print("   ℹ No scraped data found. Checking for sample files...")
        try:
            from .samples import detect_samples
            samples = detect_samples(plugin_dir)
            sample_xyz = [s for s in samples if s["type"] == "xyz_geometry"]
            if sample_xyz:
                xyz_files = [Path(s["path"]) for s in sample_xyz[:n_jobs]]
                print(f"   📄 Using {len(xyz_files)} sample file(s) from plugin directory")
        except Exception:
            pass

    if not xyz_files:
        print("❌ No input files found. Place sample .xyz files in plugins/YOUR_PLUGIN/samples/")
        return {"error": "no_xyz_files"}

    print(f"📂 Selected {len(xyz_files)} test structures:")
    for f in xyz_files:
        try:
            natoms = int(f.read_text().splitlines()[0].strip())
        except Exception:
            natoms = "?"
        print(f"   {f.name} ({natoms} atoms)")

    # Create pilot working directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pilot_dir = _get_project_root() / "data" / "output" / "pilots" / plugin_name / timestamp
    pilot_dir.mkdir(parents=True, exist_ok=True)

    # Copy selected XYZ files
    pilot_xyz = pilot_dir / "xyz"
    pilot_xyz.mkdir()
    for f in xyz_files:
        shutil.copy2(f, pilot_xyz / f.name)

    # Copy plugin contents
    for dirname in ("scripts", "templates", "glue"):
        src = plugin_dir / dirname
        if src.is_dir():
            shutil.copytree(src, pilot_dir / dirname)

    # Copy flat scripts — mirror the plugin layout
    if not (plugin_dir / "scripts").is_dir():
        scripts_dst = pilot_dir / "scripts"
        scripts_dst.mkdir(exist_ok=True)
        for f in plugin_dir.iterdir():
            if f.is_file() and f.suffix in (".sh", ".py", ".submit"):
                shutil.copy2(f, pilot_dir / f.name)
                shutil.copy2(f, scripts_dst / f.name)
    else:
        for name in ("start.sh", "run_orca_wbo.sh", "batch_job.submit"):
            src = plugin_dir / "scripts" / name
            if src.exists() and not (pilot_dir / name).exists():
                shutil.copy2(src, pilot_dir / name)

    # Copy configs
    for fname in ("plugin.yaml", "cluster.yaml", "cluster.env", "environment.yml",
                   "README.md", "WORKFLOW.md"):
        src = plugin_dir / fname
        if not src.exists():
            src = plugin_dir.parent.parent / fname
        if src.exists():
            shutil.copy2(src, pilot_dir / fname)

    # Save pilot config
    pilot_config = {
        "plugin": plugin_name,
        "scheduler": scheduler,
        "n_jobs": len(xyz_files),
        "xyz_files": [f.name for f in xyz_files],
        "timestamp": timestamp,
        "pilot_dir": str(pilot_dir),
    }
    (pilot_dir / "pilot_config.json").write_text(
        json.dumps(pilot_config, indent=2)
    )

    # Make everything executable
    for d in (pilot_dir / "glue", pilot_dir / "scripts"):
        if d.is_dir():
            for f in d.rglob("*.sh"):
                f.chmod(f.stat().st_mode | 0o755)
    for f in pilot_dir.iterdir():
        if f.is_file() and f.suffix == ".sh":
            f.chmod(f.stat().st_mode | 0o755)

    # Create a convenience "latest" symlink
    latest = pilot_dir.parent / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(pilot_dir.name)
    except OSError:
        pass

    print(f"\n📁 Pilot directory: {pilot_dir}")

    # ── Prep-only mode: stop here ─────────────────────────────────────
    if prep_only:
        print(f"\n✅ Pilot prepared. To run on the host:\n")
        print(f"   cd {pilot_dir}")
        print(f"   bash glue/prepare_and_launch.sh")
        print(f"\n   Then collect results:")
        print(f"   ./golddigr plugin pilot {plugin_name} "
              f"--pilot-dir {pilot_dir}")
        return {"status": "prepped", "pilot_dir": str(pilot_dir)}

    # ── Full mode: launch + watch + collect ───────────────────────────
    glue_dir = pilot_dir / "glue"
    entry_script = None

    if glue_dir.is_dir():
        for name in ("prepare_and_launch.sh", "submit_all.sh", "run.sh"):
            candidate = glue_dir / name
            if candidate.exists():
                entry_script = candidate
                break
        if not entry_script:
            for f in sorted(glue_dir.iterdir()):
                if f.suffix == ".sh":
                    entry_script = f
                    break

    if not entry_script:
        print("❌ No glue script found. Run 'plugin init' first.")
        return {"error": "no_glue_script"}

    print(f"\n🚀 Launching: {entry_script.name}")
    print("─" * 60)

    start_time = time.time()
    try:
        proc = subprocess.run(
            ["bash", str(entry_script)],
            cwd=str(pilot_dir),
            capture_output=True, text=True, timeout=300,
        )
        stdout = proc.stdout
        stderr = proc.stderr

        (pilot_dir / "glue_stdout.log").write_text(stdout)
        (pilot_dir / "glue_stderr.log").write_text(stderr)

        if proc.returncode != 0:
            print(f"\n❌ Glue script exited with code {proc.returncode}")
            print(f"   stderr: {stderr[:500]}")
            if "condor_submit" not in stdout and "sbatch" not in stdout:
                return {
                    "error": "glue_failed",
                    "returncode": proc.returncode,
                    "stderr": stderr[:2000],
                    "stdout": stdout[:2000],
                    "pilot_dir": str(pilot_dir),
                }
        else:
            print(f"   Glue script completed successfully")

    except subprocess.TimeoutExpired:
        print("⚠  Glue script timed out (300s). It may have launched jobs asynchronously.")

    print("─" * 60)

    return _watch_and_collect(
        pilot_dir, pilot_config, scheduler,
        poll_interval, max_wait, auto_diagnose,
        provider, model, start_time, manifest,
    )


def _watch_and_collect(
    pilot_dir, pilot_config, scheduler,
    poll_interval, max_wait, auto_diagnose,
    provider, model, start_time, manifest,
):
    """Watch for job completion and collect results."""

    if scheduler == "local":
        print("\n⏳ Local execution — checking for results...\n")
    else:
        print(f"\n⏳ Watching {scheduler} queue (poll every {poll_interval}s, max {max_wait}s)...\n")

    events = []
    wait_start = time.time()
    prev_running = -1

    while time.time() - wait_start < max_wait:
        if scheduler != "local":
            running = _count_running_jobs(scheduler)
        else:
            # For local: check if results directory is growing
            running = 0

        event = {
            "time": datetime.now().isoformat(),
            "running": running,
            "elapsed": int(time.time() - wait_start),
        }

        # Check for held jobs
        held = _get_held_jobs(scheduler)
        if held:
            event["held"] = len(held)

        events.append(event)

        # Log status changes
        if running != prev_running:
            held_str = f" ({len(held)} held)" if held else ""
            print(f"   [{event['time'][-8:]}] {running} jobs running{held_str}")
            prev_running = running

        if running == 0 and time.time() - wait_start > 30:
            print(f"\n✅ All pilot jobs completed ({int(time.time() - wait_start)}s)")
            break

        time.sleep(poll_interval)
    else:
        print(f"\n⚠  Max wait time reached ({max_wait}s). Collecting partial results.")

    # Save events
    events_path = pilot_dir / "events.jsonl"
    with open(events_path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    # ── Collect results ───────────────────────────────────────────────
    print("\n📊 Collecting results...\n")
    results = _collect_results(pilot_dir)
    results["pilot_config"] = pilot_config
    results["events"] = events
    results["elapsed"] = int(time.time() - start_time)

    # Save results
    (pilot_dir / "pilot_results.json").write_text(
        json.dumps(results, indent=2, default=str)
    )

    # Print summary
    s = results["summary"]
    print(f"   Total: {s['total']}  Passed: {s['passed']}  "
          f"Failed: {s['failed']}  Unknown: {s['unknown']}")

    for job in results["jobs"]:
        icon = "✅" if job["status"] == "passed" else "❌" if job["status"] == "failed" else "❓"
        print(f"   {icon} {job['name']}: {job['status']}")
        if job["errors"]:
            print(f"      {job['errors'][0][:80]}")

    # ── Auto-diagnose if requested ────────────────────────────────────
    if auto_diagnose and (s["failed"] > 0 or s["unknown"] > 0):
        print(f"\n🔍 Auto-diagnosing failures...")
        from .diagnose import diagnose_results
        report = diagnose_results(
            pilot_dir=pilot_dir,
            results=results,
            manifest=manifest,
            provider=provider,
            model=model,
        )
        results["diagnosis"] = report

    print(f"\n📁 Full results saved to: {pilot_dir}")

    if s["passed"] == s["total"] and s["total"] > 0:
        print(f"\n🎉 Pilot passed! To launch full run:")
        print(f"   ./golddigr plugin launch {plugin_name}")
    elif s["failed"] > 0:
        print(f"\n💡 To diagnose failures:")
        print(f"   ./golddigr plugin diagnose {plugin_name} --pilot-dir {pilot_dir}")

    return results


# ═══════════════════════════════════════════════════════════════════════
# Pilot loop generator
# ═══════════════════════════════════════════════════════════════════════

def generate_pilot_loop(
    plugin_dir: Path,
    xyz_root: Path,
    *,
    n_jobs: int = 1,
    max_iterations: int = 5,
    poll_interval: int = 60,
    provider: str = "openai",
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Prepare a pilot directory (symlink-based) and generate a host-side loop script.

    Directory layout:
      - glue/     : COPIED (auto-fix modifies these)
      - xyz/      : COPIED (pilot-specific test files)
      - scripts/  : SYMLINKED to plugin dir (read-only)
      - *.sh      : SYMLINKED to plugin dir (read-only)
      - *.submit  : SYMLINKED
      - *.yaml    : SYMLINKED
      - Everything else (inputs/, results/, job_*.txt) created by glue at runtime

    The loop script handles:
      - Job ID tracking per scheduler (SGE, SLURM, HTCondor, PBS)
      - Trap/cleanup on exit/interrupt (kills jobs, tmux, lingering processes)
      - Wait based on tracked job IDs, not prefix grep
    """
    plugin_dir = Path(plugin_dir).resolve()
    manifest = load_manifest(plugin_dir)
    plugin_name = manifest.get("name", "unknown")
    scheduler = manifest.get("scheduler", _detect_scheduler())

    _PILOT_HARD_CAP = 10
    if n_jobs > _PILOT_HARD_CAP:
        print(f"⚠  Max {_PILOT_HARD_CAP} pilot jobs.")
        n_jobs = _PILOT_HARD_CAP

    print(f"\n🧪 Pilot loop: {plugin_name}")
    print(f"   Scheduler: {scheduler}")
    print(f"   Jobs: {n_jobs}")
    print(f"   Max iterations: {max_iterations}\n")

    # Pick representative files
    xyz_files = _pick_representative_files(xyz_root, n_jobs)
    if not xyz_files:
        # Fallback: check for sample files in the plugin directory
        print("   ℹ No scraped data found. Checking for sample files...")
        try:
            from .samples import detect_samples
            samples = detect_samples(plugin_dir)
            sample_xyz = [s for s in samples if s["type"] == "xyz_geometry"]
            if sample_xyz:
                xyz_files = [Path(s["path"]) for s in sample_xyz[:n_jobs]]
                print(f"   📄 Using {len(xyz_files)} sample file(s) from plugin directory")
        except Exception:
            pass

    if not xyz_files:
        print("❌ No input files found. Either:")
        print("   - Run the scrape pipeline first to populate data/output/xyz/")
        print("   - Place sample .xyz files in plugins/YOUR_PLUGIN/samples/")
        return {"error": "no_input_files"}

    print(f"📂 Selected {len(xyz_files)} test structures:")
    for f in xyz_files:
        try:
            natoms = int(f.read_text().splitlines()[0].strip())
        except Exception:
            natoms = "?"
        print(f"   {f.name} ({natoms} atoms)")

    # Create pilot directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pilot_dir = _get_project_root() / "data" / "output" / "pilots" / plugin_name / timestamp
    pilot_dir.mkdir(parents=True, exist_ok=True)

    # ── Symlink-based prep ────────────────────────────────────────────
    # Compute relative path from pilot_dir to plugin_dir for symlinks
    rel_to_plugin = os.path.relpath(plugin_dir, pilot_dir)

    # COPY: glue/ (auto-fix will modify these)
    glue_src = plugin_dir / "glue"
    if glue_src.is_dir():
        shutil.copytree(glue_src, pilot_dir / "glue")

    # COPY: xyz/ (pilot-specific test files)
    pilot_xyz = pilot_dir / "xyz"
    pilot_xyz.mkdir()
    for f in xyz_files:
        shutil.copy2(f, pilot_xyz / f.name)

    # SYMLINK: scripts/ directory
    scripts_src = plugin_dir / "scripts"
    if scripts_src.is_dir():
        (pilot_dir / "scripts").symlink_to(os.path.relpath(scripts_src, pilot_dir))

    # SYMLINK: individual files at plugin root (flat layout)
    symlink_exts = (".sh", ".py", ".submit", ".yaml", ".yml", ".md")
    for f in plugin_dir.iterdir():
        if f.is_file() and f.suffix in symlink_exts:
            target = pilot_dir / f.name
            if not target.exists():
                target.symlink_to(os.path.relpath(f, pilot_dir))

    # SYMLINK: templates/ if exists
    templates_src = plugin_dir / "templates"
    if templates_src.is_dir():
        (pilot_dir / "templates").symlink_to(os.path.relpath(templates_src, pilot_dir))

    # Create empty dirs
    (pilot_dir / "logs").mkdir(exist_ok=True)

    # Save pilot config
    (pilot_dir / "pilot_config.json").write_text(json.dumps({
        "plugin": plugin_name, "scheduler": scheduler,
        "n_jobs": len(xyz_files), "timestamp": timestamp,
        "max_iterations": max_iterations,
        "plugin_dir": str(plugin_dir),
    }, indent=2))

    # Make glue scripts executable
    glue_dir = pilot_dir / "glue"
    if glue_dir.is_dir():
        for f in glue_dir.rglob("*.sh"):
            f.chmod(f.stat().st_mode | 0o755)

    # Latest symlink
    latest = pilot_dir.parent / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    try:
        latest.symlink_to(pilot_dir.name)
    except OSError:
        pass

    # Find glue entry script
    glue_entry = "glue/prepare_and_launch.sh"
    gd = pilot_dir / "glue"
    if gd.is_dir():
        for name in ("prepare_and_launch.sh", "submit_all.sh", "run.sh"):
            if (gd / name).exists():
                glue_entry = f"glue/{name}"
                break

    project_root = _get_project_root()
    try:
        pilot_rel = str(pilot_dir.relative_to(project_root))
    except ValueError:
        # Fallback: use relpath
        pilot_rel = os.path.relpath(pilot_dir, project_root)
    n_levels = len(Path(pilot_rel).parts)
    up_path = "/".join([".."] * n_levels)

    # ── Generate pilot_loop.sh ────────────────────────────────────────
    loop_script = f'''#!/bin/bash
# Auto-generated pilot loop for: {plugin_name}
# Max iterations: {max_iterations}  |  Scheduler: {scheduler}
#
# WORKSPACE ISOLATION: each iteration runs in a fresh workspace/.
# Glue scripts (with accumulated fixes) live in the pilot root.
# The workspace is disposable — wiped and rebuilt each iteration.
#
# Usage: bash {pilot_rel}/pilot_loop.sh
set -uo pipefail  # no -e: we handle errors explicitly

PROJECT_ROOT="$(cd "$(dirname "$0")/{up_path}" && pwd)"
PILOT_DIR="$PROJECT_ROOT/{pilot_rel}"
PLUGIN_CMD="python3 $PROJECT_ROOT/plugin.py"
MAX_ITER=${{GOLDDIGR_MAX_ITER:-{max_iterations}}}
PLUGIN_NAME="{plugin_name}"
MODEL="{model}"
POLL_INTERVAL={poll_interval}
TRACKED_JOBS_FILE="$PILOT_DIR/pilot_tracked_jobs.txt"
WORKSPACE="$PILOT_DIR/workspace"
CLEANUP_DONE=0

cd "$PROJECT_ROOT"

if [[ ! -f "$PROJECT_ROOT/plugin.py" ]]; then
    echo "Error: plugin.py not found at $PROJECT_ROOT/plugin.py"
    exit 1
fi

# ══════════════════════════════════════════════════════════════════
# Cleanup trap — runs ONCE on exit/interrupt
# ══════════════════════════════════════════════════════════════════
cleanup() {{
    [[ "$CLEANUP_DONE" -eq 1 ]] && return
    CLEANUP_DONE=1
    echo ""
    echo "🧹 Cleaning up pilot..."

    # 1. Kill tracked scheduler jobs
    if [[ -f "$TRACKED_JOBS_FILE" ]]; then
        while IFS= read -r jobid; do
            [[ -z "$jobid" ]] && continue
            qdel "$jobid" 2>/dev/null && echo "   Deleted SGE job $jobid" && continue
            scancel "$jobid" 2>/dev/null && echo "   Cancelled SLURM job $jobid" && continue
            condor_rm "$jobid" 2>/dev/null && echo "   Removed HTCondor job $jobid" && continue
        done < "$TRACKED_JOBS_FILE"
    fi

    # 2. Kill tmux sessions in pilot dir
    for session in $(tmux ls 2>/dev/null | cut -d: -f1); do
        session_dir=$(tmux display-message -p -t "$session" "#{{pane_current_path}}" 2>/dev/null || echo "")
        if [[ "$session_dir" == *"$PILOT_DIR"* ]]; then
            tmux kill-session -t "$session" 2>/dev/null
            echo "   Killed tmux session: $session"
        fi
    done

    # 3. Kill lingering processes (prevents NFS locks)
    if command -v lsof &>/dev/null; then
        local pids
        pids=$(lsof +D "$PILOT_DIR" 2>/dev/null | awk 'NR>1 {{print $2}}' | sort -u)
        for pid in $pids; do
            [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
            kill "$pid" 2>/dev/null && echo "   Killed process $pid"
        done
    fi

    echo "   Pilot directory: $PILOT_DIR"
    echo "   Done."
}}

trap cleanup EXIT INT TERM

# ══════════════════════════════════════════════════════════════════
# Job ID extraction
# ══════════════════════════════════════════════════════════════════
extract_job_ids() {{
    local logfile="$1"
    grep -oP 'Your job[- ]array?\\s+\\K[0-9]+' "$logfile" 2>/dev/null
    grep -oP 'Submitted batch job \\K[0-9]+' "$logfile" 2>/dev/null
    grep -oP '[0-9]+ job\\(s\\) submitted to cluster \\K[0-9]+' "$logfile" 2>/dev/null
    grep -oP '^[0-9]+(?=\\.)' "$logfile" 2>/dev/null
}}

# ══════════════════════════════════════════════════════════════════
# Count running jobs from tracked IDs
# ══════════════════════════════════════════════════════════════════
count_tracked_jobs() {{
    local running=0
    [[ ! -f "$TRACKED_JOBS_FILE" ]] && echo 0 && return

    while IFS= read -r jobid; do
        [[ -z "$jobid" ]] && continue
        if qstat -j "$jobid" &>/dev/null 2>&1; then
            running=$((running + 1)); continue
        fi
        if squeue -j "$jobid" --noheader 2>/dev/null | grep -q .; then
            running=$((running + 1)); continue
        fi
        if condor_q "$jobid" 2>/dev/null | grep -q "^$jobid"; then
            running=$((running + 1)); continue
        fi
    done < "$TRACKED_JOBS_FILE"
    echo "$running"
}}

# ══════════════════════════════════════════════════════════════════
# Build a fresh workspace from current glue + symlinked scripts
# ══════════════════════════════════════════════════════════════════
build_workspace() {{
    echo "   🔨 Building fresh workspace..."
    rm -rf "$WORKSPACE"
    mkdir -p "$WORKSPACE"

    # Copy glue (the current version with accumulated fixes)
    if [[ -d "$PILOT_DIR/glue" ]]; then
        cp -r "$PILOT_DIR/glue" "$WORKSPACE/glue"
        chmod +x "$WORKSPACE"/glue/*.sh 2>/dev/null || true
    fi

    # Symlink test XYZ files
    ln -s "$PILOT_DIR/xyz" "$WORKSPACE/xyz"

    # Symlink science scripts (read-only, from plugin dir)
    for f in "$PILOT_DIR"/*.sh "$PILOT_DIR"/*.py "$PILOT_DIR"/*.submit; do
        [[ -e "$f" ]] || continue
        fname=$(basename "$f")
        [[ "$fname" == "pilot_loop.sh" ]] && continue
        ln -sf "$f" "$WORKSPACE/$fname"
    done

    # Symlink other read-only files
    for f in "$PILOT_DIR"/plugin.yaml "$PILOT_DIR"/README.md "$PILOT_DIR"/WORKFLOW.md; do
        [[ -e "$f" ]] && ln -sf "$f" "$WORKSPACE/$(basename "$f")"
    done

    # Create working directories
    mkdir -p "$WORKSPACE/logs" "$WORKSPACE/results" "$WORKSPACE/work"

    echo "   ✅ Workspace ready: $WORKSPACE"
}}

# ══════════════════════════════════════════════════════════════════
# Snapshot workspace artifacts to logs/iteration_N/
# ══════════════════════════════════════════════════════════════════
snapshot_workspace() {{
    local iter="$1"
    local snap="$PILOT_DIR/logs/iteration_${{iter}}"
    mkdir -p "$snap"

    # Copy logs from workspace/logs/ to snapshot root
    cp -r "$WORKSPACE/logs/"* "$snap/" 2>/dev/null || true

    # Copy results (tarballs, status.json, etc.)
    if [[ -d "$WORKSPACE/results" ]]; then
        cp -r "$WORKSPACE/results" "$snap/results" 2>/dev/null || true
    fi

    # Copy work dir artifacts (logs, outputs, status — not huge binary files)
    if [[ -d "$WORKSPACE/work" ]]; then
        cd "$WORKSPACE"
        # Use tar to preserve relative paths correctly
        find work/ -type f \\( \\
            -name "*.log" -o -name "*.out" -o -name "*.err" \\
            -o -name "*.json" -o -name "*.txt" -o -name "*.env" \\
            -o -name "*.o[0-9]*" -o -name "*.e[0-9]*" \\
        \\) 2>/dev/null | tar cf - -T - 2>/dev/null | (cd "$snap" && tar xf -) 2>/dev/null || true
        cd "$PILOT_DIR"
    fi

    # Copy any SGE/SLURM output files at workspace root
    for f in "$WORKSPACE"/*.o[0-9]* "$WORKSPACE"/*.e[0-9]*; do
        [[ -f "$f" ]] && cp "$f" "$snap/" 2>/dev/null || true
    done

    echo "   📸 Snapshot saved: $snap"
}}

# ══════════════════════════════════════════════════════════════════

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Pilot Loop: {plugin_name}"
echo "║  Max iterations: $MAX_ITER  |  Scheduler: {scheduler}"
echo "║  Workspace isolation: ON"
echo "╚══════════════════════════════════════════════════════════════╝"

for i in $(seq 1 $MAX_ITER); do
    echo ""
    echo "══════════════════════════════════════════"
    echo "  Iteration $i / $MAX_ITER"
    echo "══════════════════════════════════════════"

    # ── Fresh workspace ──────────────────────────
    build_workspace

    # ── Clear tracked jobs from previous iteration ──
    : > "$TRACKED_JOBS_FILE"

    # ── Submit (host, in workspace) ──────────────
    echo ""
    echo "🚀 Submitting pilot jobs..."
    cd "$WORKSPACE"

    LAUNCH_EXIT=0
    bash {glue_entry} > "logs/launch.log" 2>&1 || LAUNCH_EXIT=$?
    cat "logs/launch.log"

    if [[ "$LAUNCH_EXIT" -ne 0 ]]; then
        echo ""
        echo "⚠  Launch script exited with code $LAUNCH_EXIT"
        echo "   Feeding launch error to diagnose..."
        {{
            echo "LAUNCH FAILURE (exit code $LAUNCH_EXIT)"
            echo "Script: {glue_entry}"
            echo "--- stdout+stderr ---"
            cat "logs/launch.log"
        }} > "logs/launch_error.log"
    else
        # Track submitted job IDs
        extract_job_ids "logs/launch.log" >> "$TRACKED_JOBS_FILE"
        n_tracked=$(wc -l < "$TRACKED_JOBS_FILE" 2>/dev/null || echo 0)
        echo "   Tracked $n_tracked job ID(s)"

        # ── Wait (host) ──────────────────────────
        echo ""
        echo "⏳ Waiting for jobs..."

        n_expected=0
        for jf in "$WORKSPACE"/job_*.txt "$WORKSPACE"/scripts/job_*.txt; do
            [[ -f "$jf" ]] && n_expected=$((n_expected + $(wc -l < "$jf")))
        done
        if [[ "$n_expected" -eq 0 ]]; then n_expected=1; fi
        echo "   Expecting $n_expected result(s)"

        WAIT_START=$(date +%s)
        WAIT_LOOPS=0
        WAIT_MAX={max(poll_interval * 120, 7200)}

        while true; do
            WAIT_LOOPS=$((WAIT_LOOPS + 1))

            n_results=$(find "$WORKSPACE" -name "*_results.tar.gz" 2>/dev/null | wc -l)
            n_results=$((n_results + 0))
            n_running=$(count_tracked_jobs)

            echo "   Results: $n_results / $n_expected  |  Jobs running: $n_running"

            if [[ "$n_results" -ge "$n_expected" ]]; then
                echo "   ✅ All results collected."
                break
            fi

            if [[ "$n_running" -eq 0 && "$WAIT_LOOPS" -gt 2 ]]; then
                echo "   ⚠  All jobs finished. $n_results / $n_expected results produced."
                break
            fi

            elapsed=$(( $(date +%s) - WAIT_START ))
            if [[ "$elapsed" -gt "$WAIT_MAX" ]]; then
                echo "   ⚠  Wait timeout ($WAIT_MAX s). Proceeding with partial results."
                break
            fi

            sleep $POLL_INTERVAL
        done
        echo "✅ Wait complete."
    fi

    # ── Snapshot workspace → logs/iteration_N/ ───
    snapshot_workspace "$i"

    # ── Check results (plugin-specific success check) ────
    #    glue/check_results.sh defines what "success" means for this workflow.
    #    If it passes, skip diagnose entirely — we're done.
    if [[ -x "$WORKSPACE/glue/check_results.sh" ]]; then
        echo ""
        echo "🔎 Checking results..."
        CHECK_OUTPUT=""
        CHECK_RC=0
        CHECK_OUTPUT=$(bash "$WORKSPACE/glue/check_results.sh" "$WORKSPACE" 2>&1) || CHECK_RC=$?
        echo "   $CHECK_OUTPUT"

        if [[ "$CHECK_RC" -eq 0 ]]; then
            echo ""
            echo "🎉 Pilot PASSED on iteration $i!"
            echo "   $CHECK_OUTPUT"
            echo "   Ready for: ./golddigr plugin launch $PLUGIN_NAME"
            # Save pass marker
            echo "{{\\"status\\":\\"passed\\",\\"iteration\\":$i,\\"check_output\\":\\"$CHECK_OUTPUT\\"}}" \\
                > "$PILOT_DIR/logs/iteration_$i/check_passed.json" 2>/dev/null || true
            exit 0
        else
            echo "   ⚠  check_results.sh exited $CHECK_RC — proceeding to diagnose"
        fi
    elif [[ -f "$PILOT_DIR/glue/check_results.sh" ]]; then
        # Workspace copy might not be executable; try from pilot root
        echo ""
        echo "🔎 Checking results..."
        CHECK_OUTPUT=""
        CHECK_RC=0
        CHECK_OUTPUT=$(bash "$PILOT_DIR/glue/check_results.sh" "$WORKSPACE" 2>&1) || CHECK_RC=$?
        echo "   $CHECK_OUTPUT"

        if [[ "$CHECK_RC" -eq 0 ]]; then
            echo ""
            echo "🎉 Pilot PASSED on iteration $i!"
            echo "   $CHECK_OUTPUT"
            echo "   Ready for: ./golddigr plugin launch $PLUGIN_NAME"
            echo "{{\\"status\\":\\"passed\\",\\"iteration\\":$i,\\"check_output\\":\\"$CHECK_OUTPUT\\"}}" \\
                > "$PILOT_DIR/logs/iteration_$i/check_passed.json" 2>/dev/null || true
            exit 0
        else
            echo "   ⚠  check_results.sh exited $CHECK_RC — proceeding to diagnose"
        fi
    fi

    # ── Diagnose + auto-fix (container) ──────────
    #    Diagnose reads from logs/iteration_N/ (single iteration, clean data)
    #    Symlink glue/ and fix_history.json into snapshot so auto-fix writes
    #    to the persistent copies (carried to next iteration)
    echo ""
    echo "🔍 Running diagnose + auto-fix..."

    ITER_DIR="$PILOT_DIR/logs/iteration_$i"
    ln -sf "$PILOT_DIR/glue" "$ITER_DIR/glue"
    ln -sf "$PILOT_DIR/fix_history.json" "$ITER_DIR/fix_history.json" 2>/dev/null || true
    # Also link the science scripts so diagnose can read them
    for f in "$PILOT_DIR"/*.sh "$PILOT_DIR"/*.py; do
        [[ -e "$f" ]] || continue
        fname=$(basename "$f")
        [[ "$fname" == "pilot_loop.sh" ]] && continue
        ln -sf "$f" "$ITER_DIR/$fname" 2>/dev/null || true
    done
    # Link plugin.yaml
    ln -sf "$PILOT_DIR/plugin.yaml" "$ITER_DIR/plugin.yaml" 2>/dev/null || true

    cd "$PROJECT_ROOT"
    $PLUGIN_CMD plugin diagnose "$PLUGIN_NAME" \\
        --pilot-dir "{pilot_rel}/logs/iteration_$i" \\
        --model "$MODEL" --auto-fix \\
        2>&1 | tee "$PILOT_DIR/logs/iteration_${{i}}_diagnose.log"

    # ── Check: all passed? ───────────────────────
    if [[ -f "$PILOT_DIR/logs/iteration_$i/diagnosis.json" ]]; then
        status=$(python3 -c "
import json
try:
    d = json.load(open('$PILOT_DIR/logs/iteration_$i/diagnosis.json'))
    print(d.get('status', 'unknown'))
except: print('unknown')
" 2>/dev/null || echo "unknown")

        if [[ "$status" == "all_passed" ]]; then
            echo ""
            echo "🎉 Pilot PASSED on iteration $i!"
            echo "   Ready for: ./golddigr plugin launch $PLUGIN_NAME"
            exit 0
        fi
    fi

    # ── Check: only science issues left? ─────────
    if [[ -f "$PILOT_DIR/logs/iteration_$i/autofix_report.json" ]]; then
        has_fixes=$(python3 -c "
import json
try:
    r = json.load(open('$PILOT_DIR/logs/iteration_$i/autofix_report.json'))
    print('yes' if r.get('fixes_applied', []) else 'no')
except: print('unknown')
" 2>/dev/null || echo "unknown")

        if [[ "$has_fixes" == "no" ]]; then
            echo ""
            echo "⚠  No more glue fixes. Remaining issues need human judgment."
            echo "   See: $PILOT_DIR/logs/iteration_$i/diagnosis_report.md"
            echo "   Fix history: $PILOT_DIR/fix_history.json"
            exit 0
        fi
    fi

    if [[ "$i" -lt "$MAX_ITER" ]]; then
        echo "   Fixes applied. Continuing to iteration $((i+1))..."
        sleep 5
    fi
done

echo ""
echo "❌ Max iterations ($MAX_ITER) reached."
echo "   Review latest: $PILOT_DIR/logs/iteration_$MAX_ITER/"
echo "   Fix history: $PILOT_DIR/fix_history.json"
exit 1
'''

    loop_path = pilot_dir / "pilot_loop.sh"
    loop_path.write_text(loop_script)
    loop_path.chmod(loop_path.stat().st_mode | 0o755)

    print(f"\n📁 Pilot directory: {pilot_dir}")
    print(f"📜 Loop script: {loop_path}")
    print(f"\n   Layout:")
    print(f"   ├── glue/          (copied — auto-fix modifies)")
    print(f"   ├── xyz/           (copied — {len(xyz_files)} test files)")
    for f in pilot_dir.iterdir():
        if f.is_symlink() and f.name != "scripts":
            print(f"   ├── {f.name} → (symlink)")
    print(f"   ├── logs/          (iteration snapshots)")
    print(f"   ├── workspace/     (disposable — rebuilt each iteration)")
    print(f"   └── pilot_loop.sh")
    print(f"\n✅ Run this ONE command on the host:\n")
    print(f"   bash {pilot_rel}/pilot_loop.sh\n")

    return {"status": "prepped", "pilot_dir": str(pilot_dir), "loop_script": str(loop_path)}
