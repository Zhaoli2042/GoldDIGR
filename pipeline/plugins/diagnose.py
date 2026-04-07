"""
pipeline.plugins.diagnose – LLM-powered failure diagnosis + auto-fix.

Two phases:
  Phase 1 (always): Diagnose — read logs, categorize failures, report
  Phase 2 (--auto-fix): Fix — generate patches for GLUE issues only,
           apply them, never touch user science scripts

Safety model:
  ✅ Can modify:  glue/*.sh, sge_config.env, cluster.env
  ❌ Cannot modify: run_orca_wbo.sh, start.sh, user scripts, plugin.yaml
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

from ._utils import call_llm


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: Diagnosis prompts
# ═══════════════════════════════════════════════════════════════════════

_DIAGNOSE_SYSTEM = """\
You are a computational chemistry DevOps expert.  You diagnose failures \
in HPC job submissions for chemistry workflows (ORCA, Gaussian, Multiwfn, \
xTB, pysisyphus, etc.) running on SLURM, HTCondor, SGE, or PBS clusters.

You will receive:
- The plugin manifest (plugin.yaml) describing the workflow
- The glue script that was used to prepare/submit jobs
- Output logs, error logs, and status files from failed jobs
- A summary of which jobs passed and which failed

Your job is to produce a DIAGNOSIS REPORT with this structure:

## Summary
One-paragraph overview: X/Y jobs passed, Z failed.

## Failure Categories
Group failures by ROOT CAUSE, not by job name. For each category:
- **Category name** (N jobs affected)
- **Root cause**: What went wrong and why
- **Evidence**: Key error messages from the logs
- **Classification**: Is this a GLUE issue (data format, submission config) \
or a SCIENCE issue (wrong method, basis set, electronic state)?
- **Fix**: Specific, actionable fix. Include exact commands, file edits, \
or code changes when possible.

## Recommendations
- Should the user re-run the pilot after applying fixes?
- Are there structural issues that will affect the full run?
- Any performance concerns (memory, wall time, disk)?

RULES:
- Be SPECIFIC. Don't say "check the input file" — say "add 'ECP{def2-TZVP}' \
to line 3 of the ORCA input template for structures containing Au, Pt, Ir."
- Categorize errors. If 28 jobs fail the same way, that's ONE category.
- Distinguish glue from science. Glue issues can be auto-fixed. Science issues \
need human judgment.
- If you see patterns related to molecular properties (heavy elements, large \
systems, open-shell metals), mention them.

Output the report as plain text with markdown headers. No JSON.
"""


_DEBUG_SYSTEM = """\
You are a computational chemistry DevOps expert diagnosing failures from \
a PRODUCTION run (not a pilot). You may be analyzing hundreds of failures.

Same rules as pilot diagnosis, but additionally:
- Look for PATTERNS across many failures — cluster into categories
- Identify systematic issues vs. edge cases
- Prioritize: fix the category that affects the most jobs first
- For large runs, suggest batch-fix strategies (e.g., "resubmit all Fe/Co \
structures with UKS" rather than fixing one at a time)
- If a category has only 1-2 failures, it may be an edge case not worth fixing

Output format: same as pilot diagnosis, but add a "Priority" field per category \
(HIGH: >10% of jobs, MEDIUM: 1-10%, LOW: <1%).
"""


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: Auto-fix prompt
# ═══════════════════════════════════════════════════════════════════════

_AUTOFIX_SYSTEM = """\
You are a computational chemistry DevOps expert.  You have just diagnosed \
failures in a pilot run.  Now generate TARGETED PATCHES to fix the GLUE \
issues (and ONLY glue issues).

SAFETY RULES — ABSOLUTE:
1. You may ONLY modify files in the glue/ directory.
2. You may NEVER modify the user's science scripts (run_orca_wbo.sh, etc.)
3. You may NEVER modify plugin.yaml
4. You may create new files in glue/ if needed
5. You may NEVER create stub/fake runners that produce output without running \
   the actual workflow. If the real runner or entry-point is missing, the fix \
   must make it available (copy, symlink, fix path) — NOT create a fake that \
   writes placeholder output to satisfy the checker. A "skip-but-succeed" \
   path is NOT a valid fix.

CRITICAL: DO NOT REWRITE ENTIRE FILES.
Output ONLY the specific changes needed using FIND/REPLACE blocks. \
Each patch locates the exact text to change and replaces it. \
Leave all other code untouched.

If a file needs multiple changes, output multiple FIND/REPLACE blocks \
for the same file.

If a file is brand new (doesn't exist yet), use NEWFILE instead.

CLASSIFICATION FILTER:
- GLUE issues (path errors, scheduler config, missing dirs, file format): FIX
- SCIENCE issues (basis set, method, charge, convergence): SKIP

ASKING THE USER:
If a fix requires info you cannot determine from the logs (container paths, \
queue names, etc.), use ASK blocks:

=== ASK: variable_name ===
Question: Clear, specific question for the user.
Default: A reasonable default or "none"
Example: An example value

OUTPUT FORMAT:

=== FIX: glue/filename.sh ===
FIND:
  if [ -z "${ZIP_ABS}" ] || [ ! -f "$ZIP_ABS" ]; then
    echo "Error: ZIP_ABS not set."
    exit 1
  fi
REPLACE:
  zip_abs="${job_dir}/${base}.zip"
  ( cd "$jobdir" && zip -q -r "$(basename "$zip_abs")" "input.xyz" )
REASON: The launcher should create zips from XYZ, not require a pre-existing ZIP_ABS.

=== FIX: glue/filename.sh ===
FIND:
  qsub -cwd "$TASK_WRAPPER"
REPLACE:
  cd "$job_dir" && qsub -cwd -V "$TASK_WRAPPER"
REASON: Jobs must start in the job directory, not the pilot root.

=== NEWFILE: glue/helper.py ===
#!/usr/bin/env python3
...complete new file content...

=== SKIP: Category name ===
Reason: This is a science issue requiring human judgment.

RULES:
- FIND text must be EXACTLY as it appears in the current file (copy-paste)
- FIND text must be unique within the file (include enough context lines)
- REPLACE text is what it should become
- Each FIND/REPLACE block must include a REASON line
- Fix ALL glue issues, not just one
- If the on-disk file is marked "(TRUNCATED for prompt)" in the evidence, \
  do NOT assume the file is broken — only the prompt view was shortened
- Preserve all functionality that is working — ONLY change what's broken
- For SGE: always use $SGE_O_WORKDIR instead of $(dirname "$0") in job scripts
"""


# ═══════════════════════════════════════════════════════════════════════
# Evidence builder
# ═══════════════════════════════════════════════════════════════════════

def _truncate(content: str, max_chars: int) -> str:
    """Truncate content with explicit marker so LLM doesn't think the file is broken."""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + (
        f"\n\n... (TRUNCATED at {max_chars} chars for prompt — "
        f"actual file is {len(content)} chars and may be longer/complete on disk) ..."
    )


def _build_evidence_prompt(
    pilot_dir: Path,
    results: Dict[str, Any],
    manifest: Dict[str, Any],
    glue_content: str = "",
) -> str:
    parts = []

    parts.append(f"=== plugin.yaml ===\n{yaml.dump(manifest, default_flow_style=False)}\n=== END ===\n")

    if glue_content:
        parts.append(f"=== GLUE SCRIPTS ===\n{_truncate(glue_content, 8000)}\n=== END ===\n")

    s = results.get("summary", {})
    parts.append(f"=== RESULTS SUMMARY ===")
    parts.append(f"Total: {s.get('total', '?')}  Passed: {s.get('passed', '?')}  "
                 f"Failed: {s.get('failed', '?')}  Unknown: {s.get('unknown', '?')}")
    parts.append(f"=== END ===\n")

    for job in results.get("jobs", []):
        if job["status"] == "passed":
            parts.append(f"=== JOB: {job['name']} — PASSED ===\n(no issues)\n=== END ===\n")
            continue

        parts.append(f"=== JOB: {job['name']} — {job['status'].upper()} ===")

        if job.get("errors"):
            parts.append("Key errors:")
            for err in job["errors"][:10]:
                parts.append(f"  {err}")

        for ftype, finfo in job.get("files", {}).items():
            content = finfo.get("content", "")
            if content:
                lines = content.splitlines()
                if len(lines) > 40:
                    relevant = lines[:10] + ["... (truncated) ..."] + lines[-20:]
                else:
                    relevant = lines
                parts.append(f"\n--- {ftype}: {finfo.get('path', '?')} ---")
                parts.append("\n".join(relevant))

        parts.append(f"=== END ===\n")

    for logname in ("glue_stdout.log", "glue_stderr.log", "launch.log", "launch_error.log"):
        logpath = pilot_dir / logname
        if logpath.exists():
            content = _truncate(logpath.read_text(errors="ignore"), 3000)
            if content.strip():
                parts.append(f"=== {logname} ===\n{content}\n=== END ===\n")

    # Include launch error logs from various layouts
    logs_dir = pilot_dir / "logs"
    if logs_dir.is_dir():
        for pattern in ("launch_error_*.log", "launch_error*.log",
                         "iteration_*_launch.log", "*.log"):
            for logpath in sorted(logs_dir.glob(pattern)):
                content = _truncate(logpath.read_text(errors="ignore"), 3000)
                if content.strip():
                    parts.append(f"=== {logpath.name} ===\n{content}\n=== END ===\n")

    # Include SGE/SLURM output from work/ subdirectories
    work_dir = pilot_dir / "work"
    if work_dir.is_dir():
        for f in sorted(work_dir.rglob("*.o[0-9]*"))[:10]:
            content = _truncate(f.read_text(errors="ignore"), 2000)
            if content.strip():
                parts.append(f"=== SGE stdout: {f.relative_to(pilot_dir)} ===\n{content}\n=== END ===\n")
        for f in sorted(work_dir.rglob("*.e[0-9]*"))[:10]:
            content = _truncate(f.read_text(errors="ignore"), 2000)
            if content.strip():
                parts.append(f"=== SGE stderr: {f.relative_to(pilot_dir)} ===\n{content}\n=== END ===\n")
        for f in sorted(work_dir.rglob("*.log"))[:5]:
            content = _truncate(f.read_text(errors="ignore"), 2000)
            if content.strip():
                parts.append(f"=== work log: {f.relative_to(pilot_dir)} ===\n{content}\n=== END ===\n")

    prompt = "\n".join(parts)
    if len(prompt) > 100_000:
        prompt = prompt[:100_000] + "\n... (truncated)"
    return prompt


# ═══════════════════════════════════════════════════════════════════════
# Auto-fix: parse and apply patches
# ═══════════════════════════════════════════════════════════════════════

def _parse_fixes(raw: str) -> Dict[str, Any]:
    """
    Parse LLM auto-fix output with FIND/REPLACE patches.

    Returns:
      {
        "patches": [{"file": "glue/x.sh", "find": "...", "replace": "...", "reason": "..."}],
        "newfiles": {"glue/helper.py": "content..."},
        "skips": [{"category": ..., "reason": ...}],
        "asks": [{"variable": ..., "question": ..., "default": ..., "example": ...}],
      }
    """
    result: Dict[str, Any] = {"patches": [], "newfiles": {}, "skips": [], "asks": []}

    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    # Split on === FIX: ... ===, === NEWFILE: ... ===, === SKIP: ... ===, === ASK: ... ===
    parts = re.split(r"^=== (FIX|NEWFILE|SKIP|ASK):\s*(.+?)\s*===\s*$", raw, flags=re.MULTILINE)

    i = 1
    while i < len(parts) - 2:
        block_type = parts[i]
        name = parts[i + 1]
        content = parts[i + 2]

        # Trim content at the next === marker
        for marker in ("=== FIX:", "=== NEWFILE:", "=== SKIP:", "=== ASK:"):
            idx = content.find(marker)
            if idx >= 0:
                content = content[:idx]
        content = content.strip()

        if block_type == "FIX":
            # Parse FIND/REPLACE blocks within this FIX
            # There may be multiple FIND/REPLACE pairs for the same file
            find_replace_parts = re.split(r'^FIND:\s*$', content, flags=re.MULTILINE)

            for fr_block in find_replace_parts[1:]:  # skip text before first FIND
                # Split FIND from REPLACE
                replace_split = re.split(r'^REPLACE:\s*$', fr_block, flags=re.MULTILINE)
                if len(replace_split) < 2:
                    continue

                find_text = replace_split[0].strip()
                rest = replace_split[1]

                # Extract REASON if present
                reason_match = re.search(r'^REASON:\s*(.+)$', rest, re.MULTILINE)
                reason = reason_match.group(1).strip() if reason_match else ""
                if reason_match:
                    replace_text = rest[:reason_match.start()].strip()
                else:
                    replace_text = rest.strip()

                # Strip leading indentation that the LLM adds for formatting
                # (the FIND/REPLACE content may have consistent leading spaces
                #  from the prompt format, but the actual file doesn't)
                find_text = _strip_uniform_indent(find_text)
                replace_text = _strip_uniform_indent(replace_text)

                if find_text:
                    result["patches"].append({
                        "file": name,
                        "find": find_text,
                        "replace": replace_text,
                        "reason": reason,
                    })

            # Fallback: if no FIND/REPLACE found, treat entire content as a complete file
            # (backward compatibility with LLMs that ignore the FIND/REPLACE instruction)
            if not result["patches"] or all(p["file"] != name for p in result["patches"]):
                # Check if content looks like a complete file (starts with shebang)
                if content.startswith("#!/") or content.startswith("import ") or content.startswith("#!"):
                    result["newfiles"][name] = content + "\n"

        elif block_type == "NEWFILE":
            result["newfiles"][name] = content + "\n"

        elif block_type == "SKIP":
            result["skips"].append({"category": name, "reason": content})

        elif block_type == "ASK":
            ask_info = {"variable": name, "question": "", "default": "none", "example": ""}
            for line in content.splitlines():
                line = line.strip()
                if line.lower().startswith("question:"):
                    ask_info["question"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("default:"):
                    ask_info["default"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("example:"):
                    ask_info["example"] = line.split(":", 1)[1].strip()
                elif not ask_info["question"] and line:
                    ask_info["question"] = line
            result["asks"].append(ask_info)

        i += 3

    return result


def _strip_uniform_indent(text: str) -> str:
    """Remove uniform leading whitespace from all lines (like textwrap.dedent but simpler)."""
    lines = text.splitlines()
    if not lines:
        return text
    # Find minimum indent of non-empty lines
    min_indent = float('inf')
    for line in lines:
        if line.strip():
            indent = len(line) - len(line.lstrip())
            min_indent = min(min_indent, indent)
    if min_indent == float('inf') or min_indent == 0:
        return text
    return "\n".join(line[min_indent:] if len(line) >= min_indent else line for line in lines)


def _validate_fixes(parsed: Dict[str, Any], pilot_dir: Path) -> List[str]:
    """
    Validate that fixes only touch glue files.
    Returns list of rejected file paths.
    """
    rejected = []

    # Check patches
    for patch in parsed.get("patches", []):
        clean = patch["file"].strip().replace("\\", "/")
        if not (clean.startswith("glue/") or clean in ("sge_config.env", "cluster.env")):
            rejected.append(patch["file"])

    # Check newfiles
    for fpath in parsed.get("newfiles", {}):
        clean = fpath.strip().replace("\\", "/")
        if not (clean.startswith("glue/") or clean in ("sge_config.env", "cluster.env")):
            rejected.append(fpath)

    return rejected


def _apply_fixes(
    parsed: Dict[str, Any],
    pilot_dir: Path,
) -> List[str]:
    """
    Apply FIND/REPLACE patches and new files to the pilot directory.
    Returns list of files modified.
    """
    applied = []
    failed_patches = []

    # Backup glue directory
    glue_dir = pilot_dir / "glue"
    if glue_dir.is_dir():
        backup = pilot_dir / "glue.pre-fix.bak"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(glue_dir, backup)

    # Apply FIND/REPLACE patches
    for patch in parsed.get("patches", []):
        fpath = patch["file"].strip().replace("\\", "/")
        find_text = patch["find"]
        replace_text = patch["replace"]
        reason = patch.get("reason", "")

        target = pilot_dir / fpath
        if not target.exists():
            # If file doesn't exist, try following symlinks
            if target.is_symlink():
                real = target.resolve()
                if real.exists():
                    target = real
                else:
                    print(f"   ⚠  Skip patch: {fpath} not found")
                    failed_patches.append(f"{fpath}: file not found")
                    continue
            else:
                print(f"   ⚠  Skip patch: {fpath} not found")
                failed_patches.append(f"{fpath}: file not found")
                continue

        content = target.read_text(errors="ignore")

        # Try exact match first
        if find_text in content:
            content = content.replace(find_text, replace_text, 1)
            target.write_text(content, encoding="utf-8")
            if fpath not in applied:
                applied.append(fpath)
            if reason:
                logger.debug("Patch %s: %s", fpath, reason)
        else:
            # Try with normalized whitespace (common LLM formatting issue)
            find_normalized = " ".join(find_text.split())
            content_normalized = " ".join(content.split())
            if find_normalized in content_normalized:
                # Find the actual position in the original content
                # by matching line-by-line
                find_lines = [l.strip() for l in find_text.splitlines() if l.strip()]
                content_lines = content.splitlines()
                match_start = None
                for ci in range(len(content_lines)):
                    if content_lines[ci].strip() == find_lines[0]:
                        # Check if subsequent lines match
                        match = True
                        fi = 0
                        for offset in range(len(content_lines) - ci):
                            if fi >= len(find_lines):
                                break
                            if content_lines[ci + offset].strip() == find_lines[fi]:
                                fi += 1
                        if fi == len(find_lines):
                            match_start = ci
                            break
                if match_start is not None:
                    # Replace the matched lines
                    match_end = match_start
                    fi = 0
                    for offset in range(len(content_lines) - match_start):
                        if fi >= len(find_lines):
                            break
                        if content_lines[match_start + offset].strip() == find_lines[fi]:
                            match_end = match_start + offset
                            fi += 1
                    new_lines = content_lines[:match_start] + \
                                replace_text.splitlines() + \
                                content_lines[match_end + 1:]
                    content = "\n".join(new_lines) + "\n"
                    target.write_text(content, encoding="utf-8")
                    if fpath not in applied:
                        applied.append(fpath)
                else:
                    print(f"   ⚠  Patch for {fpath}: FIND text not found (normalized match failed)")
                    failed_patches.append(f"{fpath}: FIND text not found")
            else:
                print(f"   ⚠  Patch for {fpath}: FIND text not found in file")
                failed_patches.append(f"{fpath}: FIND text not found")

    # Apply new files
    for fpath, content in parsed.get("newfiles", {}).items():
        clean = fpath.strip().replace("\\", "/")
        target = pilot_dir / clean
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if target.suffix in (".sh", ".py"):
            target.chmod(target.stat().st_mode | stat.S_IEXEC)
        applied.append(clean)

    # Make all .sh files executable
    for fpath in applied:
        target = pilot_dir / fpath
        if target.exists() and target.suffix == ".sh":
            target.chmod(target.stat().st_mode | stat.S_IEXEC)

    if failed_patches:
        print(f"   ⚠  {len(failed_patches)} patch(es) could not be applied:")
        for fp in failed_patches:
            print(f"      {fp}")

    return applied


# ═══════════════════════════════════════════════════════════════════════
# Main diagnosis function
# ═══════════════════════════════════════════════════════════════════════

def diagnose_results(
    pilot_dir: Path,
    results: Optional[Dict] = None,
    manifest: Optional[Dict] = None,
    provider: str = "openai",
    model: str = "gpt-4o",
    mode: str = "pilot",
    auto_fix: bool = False,
) -> Dict[str, Any]:
    """
    Run LLM diagnosis on pilot or production results.

    If auto_fix=True, generates and applies patches for glue issues.
    """
    pilot_dir = Path(pilot_dir).resolve()

    # Load results if not provided
    if results is None:
        results_path = pilot_dir / "pilot_results.json"
        if results_path.exists():
            results = json.loads(results_path.read_text())
        else:
            # No pilot_results.json — scan the directory directly
            print("⚠  No pilot_results.json found. Scanning directory for logs...\n")
            from ._utils import collect_results
            results = collect_results(pilot_dir)

            # If collect_results found nothing, broaden the search.
            # In workspace-isolation mode, snapshot dirs have logs at the ROOT
            # (launch.log, launch_error.log) not in a logs/ subdirectory.
            if results["summary"]["total"] == 0:
                # Scan root-level log files (workspace snapshot layout)
                root_logs = list(pilot_dir.glob("*.log"))
                # Scan logs/ subdirectory (legacy flat layout)
                logs_dir = pilot_dir / "logs"
                if logs_dir.is_dir():
                    root_logs += list(logs_dir.rglob("*.log"))
                    root_logs += list(logs_dir.rglob("*.o.*"))
                    root_logs += list(logs_dir.rglob("*.e.*"))
                    root_logs += list(logs_dir.rglob("*.out"))
                    root_logs += list(logs_dir.rglob("*.err"))
                # Scan work/ for SGE output (*.o[0-9]*, *.e[0-9]*)
                work_dir = pilot_dir / "work"
                if work_dir.is_dir():
                    root_logs += list(work_dir.rglob("*.o[0-9]*"))
                    root_logs += list(work_dir.rglob("*.e[0-9]*"))
                    root_logs += list(work_dir.rglob("*.out"))
                    root_logs += list(work_dir.rglob("*.log"))

                for lf in root_logs:
                    if not lf.is_file():
                        continue
                    content = _truncate(lf.read_text(errors="ignore"), 5000)
                    if not content.strip():
                        continue
                    job_name = lf.stem.split(".")[0]
                    job_info = {
                        "name": job_name,
                        "status": "unknown",
                        "files": {"log": {"path": str(lf.relative_to(pilot_dir)), "content": content}},
                        "errors": [],
                    }
                    for line in content.splitlines():
                        ll = line.lower()
                        if any(kw in ll for kw in ("error", "fatal", "no such file",
                                                    "not found", "abort", "failed",
                                                    "launch failure", "exit code")):
                            job_info["errors"].append(line.strip())
                            job_info["status"] = "failed"
                    results["jobs"].append(job_info)

                results["summary"]["total"] = len(results["jobs"])
                results["summary"]["failed"] = sum(1 for j in results["jobs"] if j["status"] == "failed")
                results["summary"]["unknown"] = sum(1 for j in results["jobs"] if j["status"] == "unknown")

            if results["summary"]["total"] == 0:
                print("❌ No logs or results found in the pilot directory.")
                return {"error": "no_results"}

    # Load manifest if not provided
    if manifest is None:
        manifest_path = pilot_dir / "plugin.yaml"
        if not manifest_path.exists():
            for parent in [pilot_dir.parent, pilot_dir.parent.parent]:
                candidate = parent / "plugin.yaml"
                if candidate.exists():
                    manifest_path = candidate
                    break
        if manifest_path.exists():
            manifest = yaml.safe_load(manifest_path.read_text())
        else:
            manifest = {"name": "unknown", "note": "manifest not found"}

    # Load glue script content
    glue_content = ""
    glue_dir = pilot_dir / "glue"
    if glue_dir.is_dir():
        for f in sorted(glue_dir.iterdir()):
            if f.is_file() and f.suffix in (".sh", ".env", ".py"):
                raw = f.read_text(errors='ignore')
                # Send full glue content — auto-fix needs to see everything
                # to produce accurate FIND/REPLACE patches
                glue_content += f"--- {f.name} ({len(raw)} chars, {raw.count(chr(10))} lines) ---\n{raw}\n\n"

    # Check if there's anything to diagnose
    s = results.get("summary", {})
    if s.get("failed", 0) == 0 and s.get("unknown", 0) == 0:
        report_text = "All jobs passed. No diagnosis needed."
        print(f"\n✅ {report_text}")
        return {"status": "all_passed", "report": report_text}

    # ── Phase 1: Diagnosis ────────────────────────────────────────────
    print(f"\n🔍 Analyzing {s.get('failed', 0)} failures + {s.get('unknown', 0)} unknowns...")
    evidence = _build_evidence_prompt(pilot_dir, results, manifest, glue_content)

    system = _DEBUG_SYSTEM if mode == "debug" else _DIAGNOSE_SYSTEM

    print(f"   Sending to {provider}/{model}...")
    try:
        report_text = call_llm(provider, model, system, evidence, 0.2, timeout=180)
    except Exception as e:
        logger.error("LLM API error during diagnosis: %s", e)
        print(f"❌ LLM API error: {e}")
        return {"error": str(e)}

    # Save report
    report_path = pilot_dir / "diagnosis_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    report = {
        "status": "diagnosed",
        "report": report_text,
        "report_path": str(report_path),
        "mode": mode,
        "model": f"{provider}/{model}",
        "n_failed": s.get("failed", 0),
        "n_unknown": s.get("unknown", 0),
    }

    # Print report
    print(f"\n{'═' * 60}")
    print(report_text)
    print(f"{'═' * 60}")
    print(f"\n📄 Report saved to: {report_path}")

    # ── Phase 2: Auto-fix (if requested) ──────────────────────────────
    if auto_fix:
        report["fixes"] = _run_auto_fix(
            pilot_dir, evidence, report_text, glue_content,
            manifest, provider, model,
        )

    # Save structured report
    (pilot_dir / "diagnosis.json").write_text(
        json.dumps(report, indent=2, default=str)
    )

    return report


def _load_fix_history(pilot_dir: Path) -> List[Dict]:
    """Load iteration history from fix_history.json."""
    history_path = pilot_dir / "fix_history.json"
    if history_path.exists():
        try:
            return json.loads(history_path.read_text())
        except Exception:
            return []
    return []


def _save_fix_history(pilot_dir: Path, history: List[Dict]) -> None:
    """Save iteration history to fix_history.json."""
    (pilot_dir / "fix_history.json").write_text(
        json.dumps(history, indent=2, default=str),
        encoding="utf-8",
    )


def _build_history_context(history: List[Dict]) -> str:
    """Format fix history as context for the LLM prompt."""
    if not history:
        return ""
    parts = [
        "=== FIX HISTORY (previous iterations) ===",
        f"There have been {len(history)} previous fix iteration(s).\n",
    ]
    for entry in history:
        i = entry.get("iteration", "?")
        parts.append(f"Iteration {i}:")
        parts.append(f"  Errors: {', '.join(str(e)[:80] for e in entry.get('errors_found', [])[:3])}")
        parts.append(f"  Classification: {entry.get('classification', '?')}")
        parts.append(f"  Files modified: {', '.join(entry.get('files_modified', []))}")
        parts.append(f"  Fix: {entry.get('fix_summary', '?')}")
        if entry.get("user_answers"):
            for k, v in entry["user_answers"].items():
                parts.append(f"  User provided: {k} = {v}")
        parts.append("")
    parts.extend([
        "CRITICAL RULE: Do NOT undo or modify fixes from previous iterations",
        "unless the diagnosis EXPLICITLY shows a previous fix caused a NEW problem.",
        "Build on top of previous fixes. Never regress.",
        "=== END HISTORY ===\n",
    ])
    return "\n".join(parts)


def _run_auto_fix(
    pilot_dir: Path,
    evidence: str,
    diagnosis_report: str,
    glue_content: str,
    manifest: Dict,
    provider: str,
    model: str,
) -> Dict[str, Any]:
    """
    Phase 2: Generate and apply fixes for glue issues.

    Three-step process:
      1. LLM generates fixes (may include ASK blocks for unknown values)
      2. If ASK blocks present: prompt user, substitute answers into fixes
      3. Validate and apply

    Returns dict with applied fixes and skipped science issues.
    """
    print(f"\n🔧 Auto-fix: generating patches for glue issues...\n")

    # Load iteration history
    history = _load_fix_history(pilot_dir)
    iteration = len(history) + 1
    history_context = _build_history_context(history)

    if history:
        print(f"   📜 Fix history: {len(history)} previous iteration(s)")

    # Build the fix prompt
    fix_prompt_parts = [
        f"=== DIAGNOSIS REPORT ===\n{diagnosis_report}\n=== END ===\n",
    ]
    if history_context:
        fix_prompt_parts.append(history_context)
    fix_prompt_parts.extend([
        f"=== CURRENT GLUE SCRIPTS ===\n{glue_content}\n=== END ===\n",
        f"=== plugin.yaml ===\n{yaml.dump(manifest, default_flow_style=False)}\n=== END ===\n",
        "Based on the diagnosis above, generate TARGETED fixes for GLUE issues.\n"
        "Use FIND/REPLACE blocks — do NOT rewrite entire files.\n"
        "For each fix: === FIX: glue/filename.sh === then FIND: ... REPLACE: ... REASON: ...\n"
        "For brand new files: === NEWFILE: glue/filename.sh === with full content.\n"
        "For science issues: === SKIP: category === with reason.\n"
        "For unknown values: === ASK: variable === with question.\n"
        "IMPORTANT: If file content in the evidence is marked TRUNCATED, the actual file\n"
        "on disk is complete — do NOT 'fix' the truncation.\n",
    ])
    fix_prompt = "\n".join(fix_prompt_parts)

    try:
        raw_fixes = call_llm(provider, model, _AUTOFIX_SYSTEM, fix_prompt, 0.2, timeout=180)
    except Exception as e:
        logger.error("LLM API error during auto-fix: %s", e)
        print(f"❌ LLM API error during auto-fix: {e}")
        return {"error": str(e)}

    # Save raw output for debugging
    (pilot_dir / "autofix_raw.txt").write_text(raw_fixes, encoding="utf-8")

    # Parse the output
    parsed = _parse_fixes(raw_fixes)
    patches = parsed["patches"]
    newfiles = parsed["newfiles"]
    skips = parsed["skips"]
    asks = parsed["asks"]

    has_fixes = bool(patches or newfiles)

    if not has_fixes and not skips and not asks:
        print("⚠  LLM returned no fixes, skips, or questions.")
        return {"error": "no_fixes_parsed"}

    # ── Handle ASK blocks ─────────────────────────────────────────────
    answers: Dict[str, str] = {}
    if asks:
        print("📋 The auto-fix needs some information:\n")
        for ask in asks:
            var = ask["variable"]
            question = ask["question"] or f"Value for {var}?"
            default = ask["default"] if ask["default"] != "none" else ""
            example = ask["example"]

            prompt_str = f"  {question}"
            if example:
                prompt_str += f"\n    Example: {example}"
            if default:
                prompt_str += f"\n    [{default}]: "
            else:
                prompt_str += "\n    > "

            try:
                answer = input(prompt_str).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n   Cancelled.")
                return {"error": "user_cancelled"}

            if not answer and default:
                answer = default

            if not answer:
                print(f"   ⚠  No value provided for {var}. Skipping auto-fix.")
                return {"error": f"missing_value_{var}"}

            answers[var] = answer
            print(f"   ✅ {var} = {answer}\n")

    # ── Substitute answers into patches and newfiles ──────────────────
    if answers:
        for patch in patches:
            for var, val in answers.items():
                patch["replace"] = patch["replace"].replace(f"{{{var}}}", val)
                patch["replace"] = patch["replace"].replace(f"${{{var}}}", val)
                patch["find"] = patch["find"].replace(f"{{{var}}}", val)
        for fpath in list(newfiles.keys()):
            content = newfiles[fpath]
            for var, val in answers.items():
                content = content.replace(f"{{{var}}}", val)
                content = content.replace(f"${{{var}}}", val)
            newfiles[fpath] = content

    # ── Show skips ────────────────────────────────────────────────────
    if skips:
        print("⏭  Science issues (skipped — need human judgment):")
        for skip in skips:
            print(f"   • {skip['category']}")
            reason_lines = skip["reason"].split("\n")
            for line in reason_lines[:3]:
                if line.strip():
                    print(f"     {line.strip()}")
        print()

    if not has_fixes:
        print("ℹ  No glue issues to auto-fix.")
        history.append({
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "errors_found": [s["category"] for s in skips],
            "classification": "science",
            "files_modified": [],
            "fix_summary": "No glue fixes — only science issues remain",
            "user_answers": answers,
        })
        _save_fix_history(pilot_dir, history)
        return {"fixes_applied": [], "skips": skips, "answers": answers}

    # ── Validate: reject non-glue files ───────────────────────────────
    rejected = _validate_fixes(parsed, pilot_dir)
    if rejected:
        print(f"🚫 Rejected fix(es) for non-glue files:")
        for r in rejected:
            print(f"   ❌ {r}")
        # Remove rejected patches
        patches = [p for p in patches if p["file"] not in rejected]
        newfiles = {k: v for k, v in newfiles.items() if k not in rejected}
        parsed["patches"] = patches
        parsed["newfiles"] = newfiles

    if not patches and not newfiles:
        print("⚠  All fixes were rejected.")
        return {"fixes_applied": [], "skips": skips, "rejected": rejected}

    # ── Show what will be changed ─────────────────────────────────────
    n_total = len(patches) + len(newfiles)
    print(f"📝 Fixes to apply ({n_total} change(s)):\n")
    for patch in patches:
        find_lines = patch["find"].count("\n") + 1
        replace_lines = patch["replace"].count("\n") + 1
        print(f"   ✏  {patch['file']}: replace {find_lines} lines → {replace_lines} lines")
        if patch.get("reason"):
            print(f"      {patch['reason'][:80]}")
    for fpath, content in newfiles.items():
        print(f"   🆕 {fpath} ({content.count(chr(10))} lines, new file)")

    # ── Apply ─────────────────────────────────────────────────────────
    print(f"\n   Applying fixes (backup: glue.pre-fix.bak/)...")
    applied = _apply_fixes(parsed, pilot_dir)

    for fpath in applied:
        print(f"   ✅ {fpath}")

    # ── Record in fix history ─────────────────────────────────────────
    error_summaries = []
    results_path = pilot_dir / "pilot_results.json"
    if results_path.exists():
        try:
            for job in json.loads(results_path.read_text()).get("jobs", []):
                for err in job.get("errors", [])[:2]:
                    error_summaries.append(str(err)[:100])
        except Exception:
            pass

    history.append({
        "iteration": iteration,
        "timestamp": datetime.now().isoformat(),
        "errors_found": error_summaries[:5] or [diagnosis_report[:200]],
        "classification": "glue",
        "files_modified": applied,
        "fix_summary": "; ".join(f"Modified {f}" for f in applied) or "No files modified",
        "user_answers": answers,
    })
    _save_fix_history(pilot_dir, history)

    # Save fix details
    fix_report = {
        "fixes_applied": applied,
        "skips": skips,
        "rejected": rejected if rejected else [],
        "answers": answers,
        "iteration": iteration,
    }
    (pilot_dir / "autofix_report.json").write_text(
        json.dumps(fix_report, indent=2, default=str)
    )

    print(f"\n✅ {len(applied)} fix(es) applied (iteration {iteration}).")
    print(f"\n   Next: re-run the pilot to test the fixes:")
    print(f"   cd {pilot_dir}")
    print(f"   bash glue/prepare_and_launch.sh")

    return fix_report


# ═══════════════════════════════════════════════════════════════════════
# Production debug
# ═══════════════════════════════════════════════════════════════════════

def diagnose_production(
    plugin_dir: Path,
    results_dir: Path,
    provider: str = "openai",
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    from ._utils import collect_results

    print(f"\n🔍 Scanning production results: {results_dir}")
    results = collect_results(results_dir)
    manifest = load_manifest_safe(plugin_dir)

    return diagnose_results(
        pilot_dir=results_dir,
        results=results,
        manifest=manifest,
        provider=provider,
        model=model,
        mode="debug",
    )


def load_manifest_safe(plugin_dir: Path) -> Dict:
    try:
        return yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    except Exception:
        return {"name": "unknown"}
