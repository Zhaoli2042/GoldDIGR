"""Shared utility functions for pipeline.plugins modules."""

import re
from typing import Any, Dict, List, Tuple


# ═══════════════════════════════════════════════════════════════════════
# LLM client
# ═══════════════════════════════════════════════════════════════════════

def call_llm(
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    *,
    timeout: int = 300,
    max_tokens: int = 8192,
) -> str:
    """Call an LLM provider and return the response text.

    Parameters
    ----------
    provider : str
        "openai" or "anthropic"
    model : str
        Model identifier (e.g. "gpt-4o", "claude-sonnet-4-20250514")
    system_prompt : str
        System-level instruction
    user_prompt : str
        User message content
    temperature : float
        Sampling temperature (default 0.2)
    timeout : int
        HTTP request timeout in seconds (default 300)
    max_tokens : int
        Max tokens for Anthropic responses (default 8192)
    """
    import os
    import requests

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": temperature,
                  "messages": [{"role": "system", "content": system_prompt},
                               {"role": "user", "content": user_prompt}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "temperature": temperature,
                  "system": system_prompt,
                  "messages": [{"role": "user", "content": user_prompt}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json().get("content", [])
        return "".join(c["text"] for c in content if c.get("type") == "text")

    raise ValueError(f"Unknown provider: {provider}")


# ═══════════════════════════════════════════════════════════════════════
# Interactive CLI helpers
# ═══════════════════════════════════════════════════════════════════════

def ask_user(question: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    prompt = f"  {question} [{default}]: " if default else f"  {question}: "
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer if answer else default


def confirm(message: str) -> bool:
    """Ask the user a yes/no question, defaulting to yes."""
    try:
        answer = input(f"  {message} [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


# ═══════════════════════════════════════════════════════════════════════
# LLM output parsing
# ═══════════════════════════════════════════════════════════════════════

def parse_multi_file_output(raw: str) -> Dict[str, str]:
    """Parse LLM output with ``=== FILE: ... ===`` markers into a dict."""
    files: Dict[str, str] = {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    parts = re.split(r"^=== FILE:\s*(.+?)\s*===\s*$", raw, flags=re.MULTILINE)
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            fname = parts[i].strip()
            content = parts[i + 1].strip() + "\n" if i + 1 < len(parts) else ""
            files[fname] = content
    elif raw.strip():
        files["glue/prepare_and_launch.sh"] = raw

    return files


# ═══════════════════════════════════════════════════════════════════════
# Shell command helpers
# ═══════════════════════════════════════════════════════════════════════

def run_cmd(cmd, cwd=None, timeout=120):
    """Run a shell command, return (exit_code, combined_output)."""
    import subprocess
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"
    except Exception as e:
        return -2, str(e)


# ═══════════════════════════════════════════════════════════════════════
# Code extraction helpers
# ═══════════════════════════════════════════════════════════════════════

def strip_fences(text: str) -> str:
    """Remove markdown code fences (```bash, ```python, etc.) from content."""
    text = text.strip()
    text = re.sub(r'^```\w*\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def extract_code_block(raw: str, language: str = "") -> str:
    """Extract first code block from LLM output."""
    pattern = rf"```{language}\s*\n(.*?)```"
    match = re.search(pattern, raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"=== FILE: .+? ===\s*\n(.*?)(?:=== (?:FILE|END)|$)",
                      raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw.strip()


def extract_multi_files(raw: str) -> Dict[str, str]:
    """Parse === FILE: path === blocks from LLM output."""
    raw = strip_fences(raw)
    files = {}
    parts = re.split(r"^=== FILE:\s*(.+?)\s*===\s*$", raw, flags=re.MULTILINE)
    i = 1
    while i < len(parts) - 1:
        name = parts[i].strip()
        content = parts[i + 1].strip()
        for marker in ("=== FILE:", "=== END"):
            idx = content.find(marker)
            if idx >= 0:
                content = content[:idx].strip()
        files[name] = strip_fences(content) + "\n"
        i += 2
    return files


# ═══════════════════════════════════════════════════════════════════════
# Scheduler detection and polling
# ═══════════════════════════════════════════════════════════════════════

def detect_scheduler() -> str:
    """Detect which scheduler is available on this system."""
    import subprocess
    for cmd, name in [("condor_q", "htcondor"), ("squeue", "slurm"), ("qstat", "sge")]:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
            return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return "local"


def count_running_jobs(scheduler: str, job_prefix: str = "golddigr-pilot") -> int:
    """Count how many pilot jobs are still running/idle/held."""
    import logging
    import os
    import subprocess
    logger = logging.getLogger(__name__)
    try:
        if scheduler == "htcondor":
            result = subprocess.run(
                ["condor_q", "-nobatch", "-constraint",
                 f'JobBatchName == "{job_prefix}"', "-totals"],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.splitlines():
                if "jobs;" in line:
                    parts = line.split(";")[0].strip().split()
                    total = int(parts[0])
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


def get_held_jobs(scheduler, job_prefix="golddigr-pilot"):
    """Get details about held/failed jobs."""
    import logging
    import os
    import subprocess
    logger = logging.getLogger(__name__)
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


def pick_representative_files(xyz_dir, n=3):
    """
    Pick N representative XYZ files — first, middle, last.
    This gives diversity: small molecules, medium, large/complex.
    """
    from pathlib import Path
    xyz_dir = Path(xyz_dir)
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
    while len(indices) < n:
        step = len(all_xyz) // (n + 1)
        for i in range(1, n + 1):
            idx = i * step
            if idx not in indices and idx < len(all_xyz):
                indices.append(idx)
            if len(indices) >= n:
                break

    return [all_xyz[i] for i in sorted(set(indices))[:n]]


def collect_results(workdir):
    """
    Scan a working directory for results, logs, and errors.
    Unpacks result tarballs and zips into temp dirs to read contents.
    Returns a structured dict suitable for LLM diagnosis.
    """
    import json
    import tarfile
    import tempfile
    import zipfile
    from pathlib import Path
    from typing import Any, Dict, List, Tuple

    workdir = Path(workdir)

    results: Dict[str, Any] = {
        "jobs": [],
        "summary": {"total": 0, "passed": 0, "failed": 0, "unknown": 0},
    }

    results_dir = workdir / "results"
    logs_dir = workdir / "logs"

    job_outputs = []

    if results_dir.is_dir():
        for f in sorted(results_dir.rglob("*_results.tar.gz")):
            job_outputs.append(("result_tarball", f))
        for f in sorted(results_dir.rglob("*.out")):
            job_outputs.append(("stdout", f))

    for f in sorted(workdir.glob("*.out")):
        job_outputs.append(("stdout", f))
    for f in sorted(workdir.glob("*.err")):
        job_outputs.append(("stderr", f))
    for f in sorted(workdir.glob("*.log")):
        if f.is_file():
            job_outputs.append(("log", f))

    if logs_dir.is_dir():
        for f in sorted(logs_dir.rglob("*.out")):
            job_outputs.append(("log", f))
        for f in sorted(logs_dir.rglob("*.err")):
            job_outputs.append(("log_err", f))
        for f in sorted(logs_dir.rglob("*.o.*")):
            if f.is_file():
                job_outputs.append(("log", f))
        for f in sorted(logs_dir.rglob("*.e.*")):
            if f.is_file():
                job_outputs.append(("log_err", f))
        for f in sorted(logs_dir.rglob("*.log")):
            if f.is_file():
                job_outputs.append(("log", f))

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

    for f in sorted(workdir.rglob("status.json")):
        try:
            json.loads(f.read_text())
            job_outputs.append(("status_json", f))
        except Exception:
            pass

    _extracted_outputs: List[Tuple[str, str, str]] = []

    for otype, fpath in list(job_outputs):
        if otype != "result_tarball":
            continue

        job_stem = fpath.stem.replace("_results.tar", "").replace("_results", "")
        job_stem = job_stem.split(".")[0]

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)

                if fpath.name.endswith(".tar.gz") or fpath.name.endswith(".tgz"):
                    with tarfile.open(fpath, "r:gz") as tf:
                        safe_members = [
                            m for m in tf.getmembers()
                            if m.isfile()
                            and not m.name.startswith("/")
                            and ".." not in m.name
                        ]
                        tf.extractall(tmpdir, members=safe_members)

                for inner in tmpdir_path.rglob("*"):
                    if not inner.is_file():
                        continue

                    if inner.name == "status.json":
                        content = inner.read_text(errors="ignore")[:5000]
                        _extracted_outputs.append((job_stem, "packed_status_json", content))

                    elif inner.suffix == ".out" and inner.stat().st_size < 500_000:
                        content = inner.read_text(errors="ignore")[:5000]
                        _extracted_outputs.append((job_stem, f"packed_orca_out:{inner.name}", content))

                    elif inner.name.endswith("_log.out"):
                        content = inner.read_text(errors="ignore")[:3000]
                        _extracted_outputs.append((job_stem, f"packed_log:{inner.name}", content))

                    elif inner.suffix == ".inp" and inner.stat().st_size < 50_000:
                        content = inner.read_text(errors="ignore")[:3000]
                        _extracted_outputs.append((job_stem, f"packed_inp:{inner.name}", content))

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
            import logging
            logging.getLogger(__name__).debug("Failed to unpack %s: %s", fpath, e)

    job_files: Dict[str, list] = {}
    for output_type, filepath in job_outputs:
        name = filepath.stem
        for suffix in ("_results", ".tar"):
            name = name.replace(suffix, "")
        name = name.split(".")[0]

        if name not in job_files:
            job_files[name] = []
        job_files[name].append((output_type, filepath))

    extracted_by_job: Dict[str, List[Tuple[str, str]]] = {}
    for job_stem, ftype, content in _extracted_outputs:
        if job_stem not in extracted_by_job:
            extracted_by_job[job_stem] = []
        extracted_by_job[job_stem].append((ftype, content))
        if job_stem not in job_files:
            job_files[job_stem] = []

    _ERROR_KEYWORDS = (
        "error", "fatal", "abort", "failed", "killed",
        "no such file", "not found", "convergence",
        "exceeded", "timeout", "orca failed",
        "segmentation fault", "bus error", "core dumped",
    )

    for job_name, file_list in sorted(job_files.items()):
        job_info: Dict[str, Any] = {
            "name": job_name,
            "files": {},
            "status": "unknown",
            "errors": [],
            "has_result_tarball": False,
        }

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

        if job_info["errors"]:
            job_info["status"] = "failed"
        elif job_info["has_result_tarball"]:
            job_info["status"] = "passed"

        del job_info["has_result_tarball"]
        results["jobs"].append(job_info)

    results["summary"]["total"] = len(results["jobs"])
    for job in results["jobs"]:
        if job["status"] == "passed":
            results["summary"]["passed"] += 1
        elif job["status"] == "failed":
            results["summary"]["failed"] += 1
        else:
            results["summary"]["unknown"] += 1

    return results


def extract_job_ids_from_output(output):
    """Extract scheduler job IDs from launch output. Works for SGE, SLURM, HTCondor, PBS."""
    ids = []

    for m in re.finditer(r'Your job(?:-array)?\s+(\d+)', output):
        ids.append(m.group(1))

    for m in re.finditer(r'Submitted batch job\s+(\d+)', output):
        ids.append(m.group(1))

    for m in re.finditer(r'submitted to cluster\s+(\d+)', output):
        ids.append(m.group(1))

    for m in re.finditer(r'^(\d+)\.', output, re.MULTILINE):
        ids.append(m.group(1))

    for m in re.finditer(r'job[_-]?id[=:]\s*(\d+)', output, re.IGNORECASE):
        if m.group(1) not in ids:
            ids.append(m.group(1))

    return list(dict.fromkeys(ids))


def is_job_running(job_id: str) -> bool:
    """Check if a scheduler job is still active."""
    import shutil
    import subprocess

    if shutil.which("qstat"):
        rc = subprocess.call(["qstat", "-j", job_id],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if rc == 0:
            return True

    if shutil.which("squeue"):
        try:
            out = subprocess.check_output(
                ["squeue", "-j", job_id, "--noheader"], text=True, stderr=subprocess.DEVNULL
            )
            if out.strip():
                return True
        except subprocess.CalledProcessError:
            pass

    if shutil.which("condor_q"):
        try:
            out = subprocess.check_output(
                ["condor_q", job_id], text=True, stderr=subprocess.DEVNULL
            )
            if re.search(rf'^{job_id}', out, re.MULTILINE):
                return True
        except subprocess.CalledProcessError:
            pass

    return False


def wait_for_jobs(job_ids, poll_interval=60, timeout=7200):
    """Wait for all scheduler jobs to finish."""
    import time
    start = time.time()
    polls = 0

    while True:
        polls += 1
        running = [jid for jid in job_ids if is_job_running(jid)]

        if not running:
            if polls > 1:
                print(f"   ✅ All {len(job_ids)} job(s) finished.")
                return
        else:
            elapsed = int(time.time() - start)
            print(f"   Jobs running: {len(running)}/{len(job_ids)} "
                  f"(elapsed: {elapsed}s)")

        if time.time() - start > timeout:
            print(f"   ⚠  Timeout ({timeout}s). {len(running)} job(s) still running.")
            return

        time.sleep(poll_interval)


def fix_yaml_quoting(yaml_text: str) -> str:
    """Fix common YAML issues — mainly unquoted values containing colons.

    E.g.: ``description: count electrons: if even -> 1``
    becomes: ``description: "count electrons: if even -> 1"``
    """
    fixed_lines = []
    for line in yaml_text.splitlines():
        stripped = line.lstrip()

        # Skip comments, blank lines, block scalars, already-quoted lines
        if (not stripped or stripped.startswith("#") or
                stripped.startswith("-") and ":" not in stripped):
            fixed_lines.append(line)
            continue

        # Match: "  key: value" where value contains another colon
        # But skip lines that are already quoted, use >, |, or are list items
        m = re.match(r'^(\s*)([\w_.-]+):\s+(.+)$', line)
        if m:
            indent = m.group(1)
            key = m.group(2)
            value = m.group(3).strip()

            # Check if value has problematic characters and isn't already quoted
            needs_quoting = (
                ':' in value and
                not value.startswith('"') and
                not value.startswith("'") and
                not value.startswith('>') and
                not value.startswith('|') and
                not value.startswith('[') and
                not value.startswith('{')
            )

            if needs_quoting:
                # Escape existing double quotes in the value
                value_escaped = value.replace('"', '\\"')
                fixed_lines.append(f'{indent}{key}: "{value_escaped}"')
                continue

        fixed_lines.append(line)

    return "\n".join(fixed_lines)
