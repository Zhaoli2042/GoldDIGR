"""
pipeline.plugins.develop – Incremental, test-driven plugin development.

Merges init + pilot-loop into one flow:
  Phase 0: Generate minimal test input from sample (LLM writes Python → we run it)
  Phase 1: Smoke tests (container starts? tools found? script parses?)
  Phase 2: Generate + test data prep script
  Phase 3: Generate + test submission script
  Phase 4: End-to-end with minimal input
  Phase 5: Generate check_results.sh from actual output

Each phase generates ONE piece, tests it with REAL output, fixes if needed,
then moves on. The LLM sees accumulated evidence from all previous phases.

Safety:
  - Never overwrites existing files in glue/ unless --force
  - User's science scripts are read-only
  - All generated files go under glue/
"""
from __future__ import annotations

import json
import logging
import re
import signal
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_MAX_PROMPT_CHARS = 60_000
_MAX_FIX_ATTEMPTS = 3

from ._utils import (
    call_llm,
    run_cmd as _run_cmd,
    strip_fences as _strip_fences,
    extract_code_block as _extract_code_block,
    extract_multi_files as _extract_multi_files,
    extract_job_ids_from_output as _extract_job_ids_from_output,
    is_job_running as _is_job_running,
    wait_for_jobs as _wait_for_jobs,
)


def _scan_plugin(plugin_dir: Path) -> Dict[str, Any]:
    """Light scan of plugin directory. Delegates to initializer.scan_plugin_dir."""
    from .initializer import scan_plugin_dir
    return scan_plugin_dir(plugin_dir)


def _gather_context(
    plugin_dir: Path,
    plugins_root: Path,
    scan: Dict[str, Any],
) -> str:
    """Build the shared context block (library, probe, containers, catalog)."""
    parts = []

    # Probe
    try:
        from .probe import load_saved_probe, format_probe_for_prompt
        probe = load_saved_probe()
        if probe:
            parts.append(format_probe_for_prompt(probe))
    except Exception:
        pass

    # Container interfaces
    try:
        from .containers import detect_container_usage, format_containers_for_prompt
        containers = detect_container_usage(plugin_dir)
        if containers:
            parts.append(format_containers_for_prompt(containers))
    except Exception:
        pass

    # Library concepts
    try:
        from .library import find_concepts_for_workflow, format_concepts_for_prompt
        probe_data = {}
        try:
            from .probe import load_saved_probe
            probe_data = load_saved_probe() or {}
        except Exception:
            pass

        target_sched = None
        sched_list = probe_data.get("schedulers_available",
                     [probe_data.get("scheduler", "")])
        if isinstance(sched_list, list) and sched_list:
            target_sched = sched_list[0]

        fs = probe_data.get("filesystem", {})
        shared_fs = bool(fs.get("shared", False)) if isinstance(fs, dict) else False

        script_text = " ".join(s.get("content", "")[:500] for s in scan["scripts"])
        tools = [t for t in ("orca", "gaussian", "multiwfn", "xtb", "pytorch", "tensorflow")
                 if t in script_text.lower()]

        concepts = find_concepts_for_workflow(
            plugins_root, scheduler=target_sched,
            shared_fs=shared_fs, tools=tools or None,
        )
        if concepts:
            snippet_ctx = format_concepts_for_prompt(concepts, include_code=True)
            parts.append(snippet_ctx)
    except Exception:
        pass

    # Catalog
    try:
        from .catalog import load_catalog
        catalog = load_catalog(plugins_root)
        cat_plugins = catalog.get("plugins", {})
        if cat_plugins:
            parts.append(f"=== CATALOG: {len(cat_plugins)} known plugin(s) ===\n"
                         + yaml.dump(cat_plugins, default_flow_style=False,
                                     sort_keys=False, width=120)[:5000]
                         + "\n=== END CATALOG ===\n")

            # Workflow graph for this specific plugin
            from .catalog import format_workflow_graph_for_prompt
            plugin_name = plugin_dir.name
            for pname, pentry in cat_plugins.items():
                if pname == plugin_name or pname.startswith(plugin_name[:20]):
                    wg = pentry.get("workflow_graph")
                    if wg:
                        parts.append(format_workflow_graph_for_prompt(wg))
                        break
    except Exception:
        pass

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Phase 0: Generate minimal test input
# ═══════════════════════════════════════════════════════════════════════

_PHASE0_SYSTEM = """You generate MINIMAL test inputs for computational workflows. Given a sample input file, you write a Python3 script that creates the SMALLEST valid input that exercises the same code paths as the original.

RULES:
- Output a complete Python3 script (no dependencies beyond standard library   + common packages like PIL, numpy)
- The script must write the test file to a path given as sys.argv[1]
- The generated file must have IDENTICAL format/structure to the sample
- Must be VALID for the FULL workflow — not just parseable, but must produce   meaningful output when processed. Single-atom molecules cannot compute bond   orders. 1-pixel images cannot be resized. Empty CSVs cannot be analyzed.
- Should complete processing in under 2 minutes
- Print a brief explanation of what was simplified to stderr

CRITICAL: "minimal" means "smallest that exercises ALL code paths", not "smallest that parses". The test input must go through the entire workflow (compute + analysis + packaging) without the science tool rejecting it.

EXAMPLES:
- XYZ file (66 atoms) -> 3-atom H2O molecule (H2O has bonds for bond order analysis)
- ZIP containing XYZ -> ZIP with same structure but H2O inside (same charge/mult encoding)
- 4K image -> 64x64 pixel test image with same channels/format
- 100-page PDF -> 2-page PDF with a table, a figure, and some text
- 1M-row CSV -> 100-row CSV with same column names and realistic values
- HDF5 with trajectories -> HDF5 with 10 frames instead of 10000
- FASTA with 1000 sequences -> 5 short sequences (enough for alignment)

Output ONLY the Python script in a ```python block. No other text.
"""



def phase0_generate_test_input(
    plugin_dir: Path,
    scan: Dict[str, Any],
    provider: str,
    model: str,
    dev_dir: Path,
) -> Optional[Path]:
    """Generate a minimal test input from sample files."""
    print("\n📐 Phase 0: Generating minimal test input...")

    # Find samples
    samples = scan.get("samples", [])
    if not samples:
        # Look for files directly
        for ext in (".xyz", ".zip", ".csv", ".png", ".jpg", ".pdf", ".txt", ".json"):
            found = list(plugin_dir.glob(f"*{ext}"))
            if found:
                from .samples import inspect_sample
                for f in found[:3]:
                    try:
                        info = inspect_sample(f)
                        if info:
                            samples.append({"path": str(f), "type": info.get("type", "unknown"),
                                            **info})
                    except Exception:
                        pass
                break

    if not samples:
        print("   ⚠  No sample files found. Skipping minimal test input generation.")
        print("   Place a sample input file in the plugin directory.")
        return None

    # Build prompt with sample info
    parts = ["Here are the sample input files from the workflow:\n"]
    for s in samples[:3]:
        parts.append(f"--- Sample: {Path(s['path']).name} ---")
        parts.append(f"Type: {s.get('type', 'unknown')}")
        if s.get("n_atoms"):
            parts.append(f"Atoms: {s['n_atoms']}, Elements: {s.get('elements', '?')}")
        if s.get("preview"):
            parts.append(f"Preview:\n{s['preview'][:2000]}")
        if s.get("contents"):
            parts.append(f"Contents: {s['contents'][:1000]}")
        parts.append("")

    # Add user script info so LLM knows what the input needs to be valid for
    if scan["scripts"]:
        parts.append("The workflow script reads the input like this:")
        for s in scan["scripts"][:2]:
            parts.append(f"--- {s['name']} (first 50 lines) ---")
            script_lines = s["content"].splitlines()[:50]
            parts.append("\n".join(script_lines))
            parts.append("")

    if scan.get("readme"):
        parts.append(f"--- README ---\n{scan['readme'][:2000]}\n")

    parts.append(
        f"Generate a Python3 script that creates a MINIMAL test input file.\n"
        f"The script must write the output to the path given in sys.argv[1].\n"
        f"The output must be valid for the workflow described above.\n"
    )

    prompt = "\n".join(parts)

    print(f"   Asking {provider}/{model}...")
    try:
        raw = call_llm(provider, model, _PHASE0_SYSTEM, prompt, 0.3, max_tokens=8000)
    except Exception as e:
        logger.error("LLM error during test input generation: %s", e)
        print(f"   ❌ LLM error: {e}")
        return None

    script_code = _extract_code_block(raw, "python")

    # Save and run the generator script
    glue_dir = dev_dir / "glue"
    glue_dir.mkdir(exist_ok=True)
    gen_script = glue_dir / "generate_test_input.py"
    gen_script.write_text(script_code)

    # Determine output path based on sample type
    sample_name = Path(samples[0]["path"]).name
    test_input = glue_dir / f"test_{sample_name}"

    rc, output = _run_cmd(f"python3 {gen_script} {test_input}", cwd=str(glue_dir))
    if rc != 0:
        print(f"   ⚠  Test input generator failed (exit {rc}):")
        print(f"   {output[:300]}")
        # Try to fix once
        fix_prompt = (
            f"The script failed with:\n{output[:1000]}\n\n"
            f"Fix the script. Output ONLY the corrected Python in a ```python block."
        )
        try:
            raw2 = call_llm(provider, model, _PHASE0_SYSTEM, fix_prompt, 0.2, max_tokens=8000)
            script_code = _extract_code_block(raw2, "python")
            gen_script.write_text(script_code)
            rc, output = _run_cmd(f"python3 {gen_script} {test_input}", cwd=str(glue_dir))
        except Exception:
            pass

    if rc == 0 and test_input.exists():
        size = test_input.stat().st_size
        print(f"   ✅ Generated: {test_input.name} ({size} bytes)")
        return test_input
    else:
        print(f"   ⚠  Could not generate test input. Using original sample.")
        # Copy original sample as fallback
        original = Path(samples[0]["path"])
        if original.exists():
            fallback = glue_dir / original.name
            shutil.copy2(original, fallback)
            return fallback
        return None


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: Smoke tests
# ═══════════════════════════════════════════════════════════════════════

def phase1_smoke_tests(
    plugin_dir: Path,
    scan: Dict[str, Any],
    dev_dir: Path,
) -> Dict[str, Any]:
    """Quick container and tool availability checks."""
    print("\n🔥 Phase 1: Smoke tests...")
    results = {"container": None, "tools": [], "script_parse": None}

    # Detect container image
    container_image = None
    try:
        from .containers import detect_container_usage
        containers = detect_container_usage(plugin_dir)
        if containers:
            for c in containers:
                img = c.get("container_image", "")
                if img and Path(img).exists():
                    container_image = img
                    break
    except Exception:
        pass

    # Also check README for container path
    if not container_image and scan.get("readme"):
        match = re.search(r'(?:container|sif|image)[:\s]+(\S+\.sif)', scan["readme"], re.I)
        if match and Path(match.group(1)).exists():
            container_image = match.group(1)

    # Test 1: Container starts
    if container_image:
        runtime = "apptainer" if shutil.which("apptainer") else "singularity"
        if shutil.which(runtime):
            rc, out = _run_cmd(f'{runtime} exec {container_image} echo "CONTAINER_OK"', timeout=30)
            if rc == 0 and "CONTAINER_OK" in out:
                results["container"] = {"status": "ok", "image": container_image, "runtime": runtime}
                print(f"   ✅ Container starts ({runtime})")
            else:
                results["container"] = {"status": "failed", "error": out[:200]}
                print(f"   ❌ Container failed: {out[:100]}")
        else:
            results["container"] = {"status": "no_runtime"}
            print(f"   ⚠  No container runtime found (apptainer/singularity)")
    else:
        print(f"   ⚠  No container image detected")

    # Test 2: Tools available
    if results["container"] and results["container"]["status"] == "ok":
        runtime = results["container"]["runtime"]
        img = results["container"]["image"]
        # Detect tools from scripts
        all_text = " ".join(s.get("content", "") for s in scan["scripts"])
        tool_checks = []
        if "/opt/orca/orca" in all_text or "orca " in all_text.lower():
            tool_checks.append(("/opt/orca/orca", "ORCA"))
        if "Multiwfn" in all_text:
            tool_checks.append(("Multiwfn_noGUI", "Multiwfn"))
        if "python3" in all_text or "python " in all_text:
            tool_checks.append(("python3", "Python3"))
        if "gaussian" in all_text.lower() or "g16" in all_text:
            tool_checks.append(("g16", "Gaussian"))

        for tool_path, tool_name in tool_checks:
            rc, out = _run_cmd(
                f'{runtime} exec {img} which {tool_path} 2>/dev/null || '
                f'{runtime} exec {img} test -f {tool_path} && echo "FOUND"',
                timeout=15
            )
            if rc == 0 and out.strip():
                results["tools"].append({"name": tool_name, "path": tool_path, "found": True})
                print(f"   ✅ {tool_name} found: {tool_path}")
            else:
                results["tools"].append({"name": tool_name, "path": tool_path, "found": False})
                print(f"   ❌ {tool_name} not found: {tool_path}")

    # Test 3: User script parses (bash -n)
    for s in scan["scripts"]:
        if s["name"].endswith(".sh"):
            script_path = plugin_dir / s["path"]
            if script_path.exists():
                rc, out = _run_cmd(f"bash -n {script_path}", timeout=10)
                if rc == 0:
                    results["script_parse"] = {"status": "ok", "script": s["name"]}
                    print(f"   ✅ {s['name']} parses (bash -n)")
                else:
                    results["script_parse"] = {"status": "error", "script": s["name"], "error": out}
                    print(f"   ❌ {s['name']} syntax error: {out[:100]}")
                break  # Only check first .sh

    # Test 4: Scheduler available
    for sched, cmd in [("sge", "qsub"), ("slurm", "sbatch"), ("htcondor", "condor_submit")]:
        if shutil.which(cmd):
            results["scheduler"] = sched
            print(f"   ✅ Scheduler: {sched} ({cmd})")
            break
    else:
        results["scheduler"] = "local"
        print(f"   ℹ  No scheduler found — will use local execution")

    return results


# ═══════════════════════════════════════════════════════════════════════
# Phase 2-5: Incremental generation
# ═══════════════════════════════════════════════════════════════════════

_IO_CONTRACT_SYSTEM = """\
You read workflow scripts and extract their input/output contract. \
You do NOT generate code. You extract three facts:

1. SIGNAL_PATTERN: What file(s) does the workflow produce on completion? \
   Use glob syntax relative to the working directory. \
   Examples: "results.tar.gz", "results/*_results.tar.gz", "output/*.csv", "done.marker"

2. VALIDATION: How to verify the output is valid. Format: check_type:args
   Supported checks:
     json_field:<filename>:<field>:<accepted_values>
       — Extract a JSON file, check a field's value
       — Example: json_field:status.json:status:complete,partial
     file_not_empty
       — Just check the signal file is non-empty
     contains_file:<filename>
       — Check the signal file (if tar/zip) contains a specific file
       — Example: contains_file:status.json
   If the workflow writes a status/summary JSON, prefer json_field.
   If there's no status file, use file_not_empty.

3. INPUT_PATTERN: What input files does the workflow consume? \
   Glob pattern relative to working directory. \
   Examples: "xyz/*.xyz", "images/*.png", "data/*.csv"

IMPORTANT:
- Read the ACTUAL script code to find these patterns
- Look for: tar -czf, json.dump, open("status, echo > done, mv results
- The signal file is what the script creates LAST (after computation)
- If outputs are inside a tarball, SIGNAL_PATTERN is the tarball; \
  VALIDATION checks what's inside it

Output EXACTLY three lines, no explanation:
SIGNAL_PATTERN=<pattern>
VALIDATION=<check>
INPUT_PATTERN=<pattern>
"""

_CHECKER_TEMPLATE = r'''#!/bin/bash
set -uo pipefail
# Auto-generated result checker
# Contract: $1 = workspace path, exit 0 = pass, exit 1 = fail

WORKSPACE="${1:-.}"

# ── IO Contract (extracted from workflow scripts) ──
SIGNAL_PATTERN="__SIGNAL_PATTERN__"
VALIDATION="__VALIDATION__"
INPUT_PATTERN="__INPUT_PATTERN__"

# ── Count inputs ──
shopt -s nullglob
INPUTS=("$WORKSPACE"/$INPUT_PATTERN)
shopt -u nullglob
TOTAL=${#INPUTS[@]}

if [ "$TOTAL" -eq 0 ]; then
    echo "FAIL: no inputs found matching $INPUT_PATTERN"
    exit 1
fi

# ── Find output artifacts ──
shopt -s nullglob
OUTPUTS=("$WORKSPACE"/$SIGNAL_PATTERN)
shopt -u nullglob
N_OUTPUTS=${#OUTPUTS[@]}

if [ "$N_OUTPUTS" -eq 0 ]; then
    # Also search one level deeper (results/<subdir>/*_results.tar.gz)
    OUTPUTS=($(find "$WORKSPACE/results" -name "*.tar.gz" -o -name "*.zip" -o -name "*.csv" -o -name "*.json" 2>/dev/null | sort))
    N_OUTPUTS=${#OUTPUTS[@]}
fi

if [ "$N_OUTPUTS" -eq 0 ]; then
    echo "FAIL: 0/$TOTAL — no outputs matching $SIGNAL_PATTERN"
    exit 1
fi

# ── Validate each output ──
PASSED=0
FAILED=0

IFS=: read -r CHECK_TYPE CHECK_ARG1 CHECK_ARG2 CHECK_ARG3 <<< "$VALIDATION"

for artifact in "${OUTPUTS[@]}"; do
    case "$CHECK_TYPE" in
        json_field)
            # CHECK_ARG1=filename, CHECK_ARG2=field, CHECK_ARG3=accepted values
            STATUS_JSON=""
            if [[ "$artifact" == *.tar.gz || "$artifact" == *.tgz ]]; then
                STATUS_JSON=$(tar -xOzf "$artifact" "./$CHECK_ARG1" 2>/dev/null || \
                              tar -xOzf "$artifact" "$CHECK_ARG1" 2>/dev/null || echo "")
            elif [[ "$artifact" == *.zip ]]; then
                STATUS_JSON=$(unzip -p "$artifact" "$CHECK_ARG1" 2>/dev/null || echo "")
            elif [ -f "$(dirname "$artifact")/$CHECK_ARG1" ]; then
                STATUS_JSON=$(cat "$(dirname "$artifact")/$CHECK_ARG1" 2>/dev/null || echo "")
            fi

            if [ -z "$STATUS_JSON" ]; then
                FAILED=$((FAILED + 1))
                continue
            fi

            VALUE=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('$CHECK_ARG2', ''))
except:
    print('')
" <<< "$STATUS_JSON" 2>/dev/null)

            if echo ",$CHECK_ARG3," | grep -q ",$VALUE,"; then
                PASSED=$((PASSED + 1))
            else
                FAILED=$((FAILED + 1))
            fi
            ;;

        contains_file)
            # CHECK_ARG1=filename to look for inside archive
            FOUND=0
            if [[ "$artifact" == *.tar.gz || "$artifact" == *.tgz ]]; then
                tar -tzf "$artifact" 2>/dev/null | grep -q "$CHECK_ARG1" && FOUND=1
            elif [[ "$artifact" == *.zip ]]; then
                unzip -l "$artifact" 2>/dev/null | grep -q "$CHECK_ARG1" && FOUND=1
            fi
            if [ "$FOUND" -eq 1 ]; then
                PASSED=$((PASSED + 1))
            else
                FAILED=$((FAILED + 1))
            fi
            ;;

        file_not_empty)
            if [ -s "$artifact" ]; then
                PASSED=$((PASSED + 1))
            else
                FAILED=$((FAILED + 1))
            fi
            ;;

        *)
            # Unknown check type — just verify file exists
            if [ -f "$artifact" ]; then
                PASSED=$((PASSED + 1))
            else
                FAILED=$((FAILED + 1))
            fi
            ;;
    esac
done

echo "Results: $PASSED/$N_OUTPUTS passed, $FAILED failed (inputs: $TOTAL)"
[ "$PASSED" -gt 0 ] && [ "$FAILED" -eq 0 ] && exit 0
exit 1
'''


_DEVELOP_SYSTEM = """\
You are a build engineer generating workflow scripts ONE AT A TIME. \
You will be told which file to generate and what evidence exists from \
previous steps.

RULES:
- Generate EXACTLY ONE file per request (the one asked for)
- Use === FILE: path === format for output
- Use tested code from the SNIPPET LIBRARY when available
- Preserve invariants from library concepts
- Every bash script must start with:
    set -euo pipefail
    trap 'echo "GLUE ERROR at ${{BASH_SOURCE}}:$LINENO (exit=$?)" >&2' ERR
- For SGE: use $SGE_O_WORKDIR, not $(dirname $0)
- For containers with OpenMPI on SGE: export OMPI_MCA_ras=^gridengine
- NEVER modify or regenerate user scripts (files that already exist outside glue/)
- All generated files go under glue/
- Include comments explaining key decisions

MANDATORY PROBE WARNINGS:
If the infrastructure probe reports warnings, your generated scripts MUST \
include the fixes. These are NOT optional — they prevent crashes:
"""


def _generate_one_file(
    filename: str,
    purpose: str,
    accumulated_context: str,
    provider: str,
    model: str,
    dev_dir: Path,
    max_attempts: int = _MAX_FIX_ATTEMPTS,
) -> Optional[str]:
    """Generate one file, with retry on failure."""

    prompt = (
        f"{accumulated_context}\n\n"
        f"Generate EXACTLY ONE file: {filename}\n"
        f"Purpose: {purpose}\n\n"
        f"Output using === FILE: {filename} === format.\n"
        f"No other files. No explanation outside the file.\n"
    )

    for attempt in range(1, max_attempts + 1):
        try:
            raw = call_llm(provider, model, _DEVELOP_SYSTEM, prompt, 0.2, max_tokens=8000)
        except Exception as e:
            logger.error("LLM error during development phase: %s", e)
            print(f"   ❌ LLM error: {e}")
            return None

        files = _extract_multi_files(raw)
        content = files.get(filename)
        if not content:
            # Try extracting from code block
            content = _extract_code_block(raw)

        if not content:
            print(f"   ⚠  LLM didn't generate {filename} (attempt {attempt})")
            prompt += "\nYou must output the file using === FILE: ... === format.\n"
            continue

        # Strip markdown fences if present (common LLM formatting)
        content = _strip_fences(content)

        # Write file
        target = dev_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if target.suffix in (".sh", ".py"):
            target.chmod(target.stat().st_mode | 0o755)

        return content

    return None


# ═══════════════════════════════════════════════════════════════════════
# Stub detection
# ═══════════════════════════════════════════════════════════════════════

# Markers that indicate auto-fix created a fake/skip success path
_STUB_MARKERS = (
    "glue_only_runner_fallback",
    "skipping stats stage",
    "skip-but-succeed",
    "stub",
    "SKIPPED:",
    "placeholder",
    "fallback runner",
    "no real computation",
)


def _detect_stub_success(workspace: Path, launch_output: str = "") -> Optional[str]:
    """Scan workspace output files and launch output for stub/fake success markers.

    Returns a description of the stub if found, None if outputs look real.
    """
    # First check launch stdout/stderr for stub markers
    if launch_output:
        launch_lower = launch_output.lower()
        for marker in _STUB_MARKERS:
            if marker.lower() in launch_lower:
                return f"launch output contains '{marker}'"

    # Check common output locations
    scan_paths = []
    for pattern in ("results/*", "*.jsonl", "*.json", "*.ok", "*.OK"):
        scan_paths.extend(workspace.glob(pattern))
    # Also check results subdirs
    results_dir = workspace / "results"
    if results_dir.is_dir():
        scan_paths.extend(results_dir.rglob("*"))
    # Check runs/ and workspace_glue/ for per-job stubs
    for subdir_name in ("runs", "workspace_glue"):
        subdir = workspace / subdir_name
        if subdir.is_dir():
            for ext in ("*.jsonl", "*.json", "*.log", "*.out", "*.txt"):
                scan_paths.extend(subdir.rglob(ext))

    for fpath in scan_paths:
        if not fpath.is_file() or fpath.stat().st_size > 50_000:
            continue
        try:
            content = fpath.read_text(errors="ignore")
            content_lower = content.lower()
            for marker in _STUB_MARKERS:
                if marker.lower() in content_lower:
                    return f"{fpath.name} contains '{marker}'"
        except Exception:
            continue

    return None


# ═══════════════════════════════════════════════════════════════════════
# Workspace + job tracking helpers
# ═══════════════════════════════════════════════════════════════════════

def _find_test_input(plugin_dir: Path) -> Optional[Path]:
    """Find the test input generated by Phase 0 (any file, any format)."""
    glue_dir = plugin_dir / "glue"
    if not glue_dir.is_dir():
        return None

    # Look for test_* files (generated by phase 0)
    for f in sorted(glue_dir.iterdir()):
        if f.is_file() and f.name.startswith("test_"):
            return f

    return None


def _build_workspace(
    plugin_dir: Path,
    workspace: Path,
    test_input: Optional[Path],
    real_xyz_files: Optional[List[Path]] = None,
) -> None:
    """Build a fresh disposable workspace for one pilot iteration."""
    print(f"\n   🔨 Building fresh workspace...")

    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)

    # Copy glue/ (the current version with accumulated fixes)
    glue_src = plugin_dir / "glue"
    if glue_src.is_dir():
        glue_dst = workspace / "glue"
        shutil.copytree(glue_src, glue_dst)
        # Make scripts executable
        for f in glue_dst.rglob("*.sh"):
            f.chmod(f.stat().st_mode | 0o755)

    # Set up test input in xyz/
    xyz_dir = workspace / "xyz"
    xyz_dir.mkdir()

    # Real data mode: copy all XYZ files directly
    if real_xyz_files:
        for f in real_xyz_files:
            shutil.copy2(f, xyz_dir / f.name)
        print(f"   📄 Using {len(real_xyz_files)} real XYZ file(s)")
    elif test_input and test_input.exists():
        if test_input.suffix == ".xyz":
            shutil.copy2(test_input, xyz_dir / test_input.name)
            print(f"   📄 Using test input: {test_input.name}")
        elif test_input.suffix == ".zip":
            # For zip test inputs, also copy to workspace root
            # (some scripts expect the zip directly)
            shutil.copy2(test_input, workspace / test_input.name)
            # Try to extract xyz from the zip for scripts that scan xyz/
            import zipfile
            try:
                with zipfile.ZipFile(test_input) as zf:
                    for name in zf.namelist():
                        if name.endswith(".xyz"):
                            content = zf.read(name)
                            (xyz_dir / Path(name).name).write_bytes(content)
            except Exception:
                pass
            print(f"   📄 Using test input: {test_input.name}")
        else:
            # Generic: copy to both xyz/ and workspace root
            shutil.copy2(test_input, xyz_dir / test_input.name)
            shutil.copy2(test_input, workspace / test_input.name)
            print(f"   📄 Using test input: {test_input.name}")
    else:
        # Fallback: look for xyz files in the plugin dir
        for f in plugin_dir.glob("*.xyz"):
            shutil.copy2(f, xyz_dir / f.name)
        # Also check samples/
        samples_dir = plugin_dir / "samples"
        if samples_dir.is_dir():
            for f in samples_dir.glob("*.xyz"):
                shutil.copy2(f, xyz_dir / f.name)
        if list(xyz_dir.iterdir()):
            print(f"   📄 Using sample files from plugin directory")
        else:
            print(f"   ⚠  No test inputs found — scripts may fail")

    # Symlink user scripts into workspace
    symlink_exts = (".sh", ".py", ".submit", ".yaml", ".yml", ".md")
    for f in plugin_dir.iterdir():
        if f.is_file() and f.suffix in symlink_exts:
            target = workspace / f.name
            if not target.exists():
                try:
                    target.symlink_to(f.resolve())
                except OSError:
                    shutil.copy2(f, target)

    # Symlink scripts/ if exists
    scripts_dir = plugin_dir / "scripts"
    if scripts_dir.is_dir():
        ws_scripts = workspace / "scripts"
        if not ws_scripts.exists():
            try:
                ws_scripts.symlink_to(scripts_dir.resolve())
            except OSError:
                shutil.copytree(scripts_dir, ws_scripts)

    # Create working directories
    (workspace / "logs").mkdir(exist_ok=True)
    (workspace / "results").mkdir(exist_ok=True)
    (workspace / "work").mkdir(exist_ok=True)

    print(f"   ✅ Workspace ready: {workspace}")


def _snapshot_workspace(workspace: Path, iter_log: Path) -> None:
    """Copy logs and lightweight artifacts from workspace to iteration log."""

    # Copy logs/
    ws_logs = workspace / "logs"
    if ws_logs.is_dir():
        for f in ws_logs.iterdir():
            if f.is_file():
                shutil.copy2(f, iter_log / f.name)

    # Copy results/ (tarballs)
    ws_results = workspace / "results"
    if ws_results.is_dir() and any(ws_results.iterdir()):
        dst = iter_log / "results"
        dst.mkdir(exist_ok=True)
        for f in ws_results.rglob("*"):
            if f.is_file():
                rel = f.relative_to(ws_results)
                (dst / rel.parent).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst / rel)

    # Copy work/ logs (not binaries)
    ws_work = workspace / "work"
    if ws_work.is_dir():
        log_exts = {".log", ".out", ".err", ".json", ".txt", ".env"}
        for f in ws_work.rglob("*"):
            if f.is_file() and (f.suffix in log_exts or
                                re.match(r'.*\.[eo]\d+', f.name)):
                rel = f.relative_to(workspace)
                dst_file = iter_log / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst_file)

    # Copy SGE output files from workspace root
    for f in workspace.glob("*.o[0-9]*"):
        shutil.copy2(f, iter_log / f.name)
    for f in workspace.glob("*.e[0-9]*"):
        shutil.copy2(f, iter_log / f.name)

    print(f"   📸 Snapshot saved: {iter_log}")


def _save_dev_log(
    log_dir: Path, timestamp: str, plugin_dir: Path,
    provider: str, model: str, smoke: Dict,
    generated: List[str], test_input: Optional[Path],
    iteration: int, status: str,
) -> None:
    """Save development session summary."""
    dev_log = {
        "timestamp": timestamp,
        "plugin": plugin_dir.name,
        "provider": f"{provider}/{model}",
        "status": status,
        "iterations": iteration,
        "phases": {
            "smoke_tests": smoke,
            "files_generated": generated,
            "test_input": str(test_input) if test_input else None,
        },
    }
    (log_dir / "develop.json").write_text(json.dumps(dev_log, indent=2, default=str))


# ═══════════════════════════════════════════════════════════════════════
# Main develop flow
# ═══════════════════════════════════════════════════════════════════════

def develop_plugin(
    plugin_dir: Path,
    plugins_root: Path,
    provider: str = "openai",
    model: str = "gpt-4o",
    force: bool = False,
    skip_full_run: bool = False,
    poll_interval: int = 60,
    # ── Merged pilot options ──
    real_data: bool = False,
    xyz_root: Optional[Path] = None,
    n_jobs: int = 3,
    prep_only: bool = False,
    resume_dir: Optional[Path] = None,
    max_wait: int = 7200,
    # ── Merged porter option ──
    port_to: Optional[str] = None,
    # ── Merged diagnose option ──
    diagnose_only: bool = False,
    diagnose_mode: str = "pilot",
    auto_fix: bool = True,
) -> Dict[str, Any]:
    """
    Unified plugin development command.

    Modes:
      - Default: generate scaffold (via initializer) + test input + smoke tests
                 + pilot loop with auto-diagnose
      - --real-data: use real XYZ files from scraped data instead of synthetic
      - --prep-only: prepare workspace and stop (user launches manually)
      - --resume <dir>: skip generation, check results from existing directory
      - --port-to <scheduler>: port glue to target scheduler, then test
      - --diagnose-only: run diagnosis on existing results without re-generating
    """
    plugin_dir = Path(plugin_dir).resolve()
    plugins_root = Path(plugins_root)

    print(f"\n🔨 Plugin Develop: {plugin_dir.name}")
    print(f"   Provider: {provider}/{model}")

    # ── Diagnose-only mode ────────────────────────────────────────────
    if diagnose_only:
        pilot_dir = resume_dir
        if pilot_dir is None:
            # Find latest dev_logs or pilot results
            dev_logs = plugin_dir / "dev_logs"
            if dev_logs.is_dir():
                subdirs = sorted([d for d in dev_logs.iterdir() if d.is_dir()],
                                 key=lambda d: d.name, reverse=True)
                if subdirs:
                    # Find latest iteration within latest session
                    iters = sorted([d for d in subdirs[0].iterdir()
                                    if d.is_dir() and d.name.startswith("iteration_")],
                                   key=lambda d: d.name, reverse=True)
                    pilot_dir = iters[0] if iters else subdirs[0]

        if pilot_dir is None or not Path(pilot_dir).is_dir():
            print(f"   ❌ No results directory found. Specify --resume <dir>.")
            return {"error": "no_results_dir"}

        print(f"   Diagnosing: {pilot_dir}")
        from .diagnose import diagnose_results
        return diagnose_results(
            pilot_dir=Path(pilot_dir),
            provider=provider,
            model=model,
            mode=diagnose_mode,
            auto_fix=auto_fix,
        )

    # ── Resume mode: check results from existing workspace ───────────
    if resume_dir is not None:
        resume_path = Path(resume_dir).resolve()
        if not resume_path.is_dir():
            print(f"   ❌ Resume directory not found: {resume_path}")
            return {"error": "resume_dir_not_found"}

        print(f"\n🔄 Resuming from: {resume_path}")
        from ._utils import collect_results
        results = collect_results(resume_path)
        s = results["summary"]
        print(f"   Total: {s['total']}  Passed: {s['passed']}  "
              f"Failed: {s['failed']}  Unknown: {s['unknown']}")

        if s["failed"] > 0 or s["unknown"] > 0:
            print(f"\n🔍 Auto-diagnosing failures...")
            from .diagnose import diagnose_results
            diag = diagnose_results(
                pilot_dir=resume_path,
                results=results,
                provider=provider,
                model=model,
                mode="pilot",
                auto_fix=auto_fix,
            )
            results["diagnosis"] = diag

        return results

    # ── Scan ──────────────────────────────────────────────────────────
    print(f"\n🔍 Scanning plugin...")
    scan = _scan_plugin(plugin_dir)

    print(f"   README: {'yes' if scan['readme'] else 'no'}")
    print(f"   Scripts: {len(scan['scripts'])} "
          f"({', '.join(s['name'] for s in scan['scripts'])})")
    print(f"   Samples: {len(scan['samples'])}")

    if not scan["readme"] and not scan["scripts"]:
        print("   ❌ Need at least a README.md or one script to start development.")
        return {"status": "empty_plugin"}

    # ── Check for existing glue ───────────────────────────────────────
    glue_dir = plugin_dir / "glue"
    if glue_dir.is_dir() and any(glue_dir.iterdir()) and not force:
        print(f"\n   ⚠  glue/ already exists ({len(list(glue_dir.iterdir()))} files).")
        print(f"   Use --force to regenerate, or manually edit existing files.")
        print(f"   Existing: {', '.join(f.name for f in glue_dir.iterdir())}")
        print(f"   Skipping generation — proceeding to test loop.")
    else:
        # ── Use initializer for scaffold generation ───────────────────
        print(f"\n🔧 Generating plugin scaffold via initializer...")
        from .initializer import init_plugin
        init_ok = init_plugin(
            plugin_dir=plugin_dir,
            plugins_root=plugins_root,
            provider=provider,
            model=model,
            non_interactive=True,
        )
        if not init_ok:
            print("   ❌ Initializer failed to generate scaffold.")
            return {"status": "init_failed"}

        # Re-scan after init to pick up new glue files
        scan = _scan_plugin(plugin_dir)

    # ── Port-to mode: translate glue before testing ──────────────────
    if port_to:
        print(f"\n🔄 Porting glue scripts to {port_to}...")
        from .porter import port_plugin
        port_ok = port_plugin(
            plugin_dir=plugin_dir,
            target_scheduler=port_to,
            provider=provider,
            model=model,
            non_interactive=True,
        )
        if not port_ok:
            print(f"   ❌ Porting to {port_to} failed.")
            return {"status": "port_failed"}
        # Re-scan after porting
        scan = _scan_plugin(plugin_dir)

    # ── Set up dev workspace ──────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dev_dir = plugin_dir  # files written as glue/xxx.sh → plugin_dir/glue/xxx.sh
    (plugin_dir / "glue").mkdir(exist_ok=True)

    log_dir = plugin_dir / "dev_logs" / timestamp
    log_dir.mkdir(parents=True, exist_ok=True)

    # ── Gather shared context ─────────────────────────────────────────
    print(f"\n📚 Gathering context (library, probe, catalog)...")
    shared_context = _gather_context(plugin_dir, plugins_root, scan)

    # Build base context that all phases will see
    base_parts = []
    if scan["readme"]:
        base_parts.append(f"=== README ===\n{scan['readme']}\n=== END ===\n")
    for s in scan["scripts"]:
        base_parts.append(f"=== USER SCRIPT: {s['path']} ({len(s['content'])} chars) ===\n"
                          f"{s['content']}\n=== END ===\n")
    if shared_context:
        base_parts.append(shared_context)

    base_context = "\n".join(base_parts)

    # Track accumulated evidence from each phase
    evidence = []

    # ══════════════════════════════════════════════════════════════════
    # Phase 0: Test input (synthetic or real data)
    # ══════════════════════════════════════════════════════════════════
    test_input = None
    real_xyz_files = []  # used in --real-data mode

    if real_data:
        from ._utils import pick_representative_files
        if xyz_root is None:
            # Default: look for scraped data
            xyz_root = plugin_dir.parent.parent / "data" / "output" / "xyz"
        xyz_root = Path(xyz_root)
        real_xyz_files = pick_representative_files(xyz_root, n_jobs)
        if not real_xyz_files:
            # Fallback to samples in plugin dir
            try:
                from .samples import detect_samples
                samples = detect_samples(plugin_dir)
                sample_xyz = [s for s in samples if s.get("type") == "xyz_geometry"]
                if sample_xyz:
                    real_xyz_files = [Path(s["path"]) for s in sample_xyz[:n_jobs]]
            except Exception:
                pass
        if not real_xyz_files:
            print("   ❌ No real XYZ files found. Use --real-data with scraped data or samples.")
            return {"status": "no_real_data"}
        print(f"\n📂 Using {len(real_xyz_files)} real XYZ file(s):")
        for f in real_xyz_files:
            try:
                natoms = int(f.read_text().splitlines()[0].strip())
            except Exception:
                natoms = "?"
            print(f"   {f.name} ({natoms} atoms)")
        evidence.append(f"=== REAL DATA: {len(real_xyz_files)} files ===\n"
                        f"Files: {', '.join(f.name for f in real_xyz_files)}\n"
                        f"=== END ===\n")
    else:
        test_input = phase0_generate_test_input(
            plugin_dir, scan, provider, model, dev_dir
        )
        if test_input:
            evidence.append(f"=== MINIMAL TEST INPUT ===\n"
                            f"File: {test_input.name} ({test_input.stat().st_size} bytes)\n"
                            f"=== END ===\n")

    # ══════════════════════════════════════════════════════════════════
    # Phase 1: Smoke tests
    # ══════════════════════════════════════════════════════════════════
    smoke = phase1_smoke_tests(plugin_dir, scan, dev_dir)
    smoke_summary = []
    if smoke.get("container"):
        smoke_summary.append(f"Container: {smoke['container']['status']} "
                             f"({smoke['container'].get('image', '?')})")
    for t in smoke.get("tools", []):
        smoke_summary.append(f"Tool {t['name']}: {'found' if t['found'] else 'MISSING'}")
    if smoke.get("scheduler"):
        smoke_summary.append(f"Scheduler: {smoke['scheduler']}")
    evidence.append(f"=== SMOKE TEST RESULTS ===\n"
                    + "\n".join(smoke_summary) + "\n=== END ===\n")

    # ══════════════════════════════════════════════════════════════════
    # Phase 2-3: Glue scripts (already generated by initializer above)
    # ══════════════════════════════════════════════════════════════════
    # Validate that glue scripts exist and have valid syntax
    glue_dir = plugin_dir / "glue"
    for gf_name in ("prepare_and_launch.sh", "task_wrapper.sh"):
        gf_path = glue_dir / gf_name
        if gf_path.exists():
            rc, out = _run_cmd(f"bash -n {gf_path}")
            if rc == 0:
                lines = gf_path.read_text().count("\n")
                print(f"   ✅ {gf_name} syntax OK ({lines} lines)")
                evidence.append(f"=== {gf_name} PRESENT ===\n"
                                f"Lines: {lines}, syntax: valid\n=== END ===\n")
            else:
                print(f"   ⚠  {gf_name} syntax error: {out[:200]}")

    # ══════════════════════════════════════════════════════════════════
    # Phase 4: Extract IO contract → fill checker template
    # ══════════════════════════════════════════════════════════════════
    print(f"\n📋 Phase 4: Extracting IO contract from scripts...")

    # Build focused prompt: just the user scripts + README
    contract_parts = []
    if scan["readme"]:
        contract_parts.append(f"=== README ===\n{scan['readme'][:3000]}\n=== END ===\n")
    for s in scan["scripts"]:
        contract_parts.append(f"=== SCRIPT: {s['path']} ===\n{s['content']}\n=== END ===\n")
    # Also include generated glue scripts (they define where outputs go)
    for gf in ["prepare_and_launch.sh", "task_wrapper.sh"]:
        gpath = plugin_dir / "glue" / gf
        if gpath.exists():
            contract_parts.append(f"=== GLUE: {gf} ===\n"
                                  f"{gpath.read_text(errors='ignore')[:8000]}\n=== END ===\n")
    contract_prompt = "\n".join(contract_parts)

    # Extract contract (tiny LLM call — 3 lines of output)
    io_contract = {"signal": "results/*_results.tar.gz",
                   "validation": "file_not_empty",
                   "input": "xyz/*.xyz"}  # defaults

    try:
        raw_contract = call_llm(provider, model, _IO_CONTRACT_SYSTEM, contract_prompt, 0.1, max_tokens=8000)
        for line in raw_contract.strip().splitlines():
            line = line.strip()
            if line.startswith("SIGNAL_PATTERN="):
                io_contract["signal"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("VALIDATION="):
                io_contract["validation"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("INPUT_PATTERN="):
                io_contract["input"] = line.split("=", 1)[1].strip().strip('"').strip("'")

        print(f"   Signal:     {io_contract['signal']}")
        print(f"   Validation: {io_contract['validation']}")
        print(f"   Input:      {io_contract['input']}")
    except Exception as e:
        logger.warning("LLM error during IO contract generation: %s", e)
        print(f"   ⚠  LLM error: {e}. Using defaults.")

    evidence.append(f"=== IO CONTRACT ===\n"
                    f"SIGNAL_PATTERN={io_contract['signal']}\n"
                    f"VALIDATION={io_contract['validation']}\n"
                    f"INPUT_PATTERN={io_contract['input']}\n"
                    f"=== END ===\n")

    # Fill the fixed template (no LLM-generated code!)
    checker_content = _CHECKER_TEMPLATE
    checker_content = checker_content.replace("__SIGNAL_PATTERN__", io_contract["signal"])
    checker_content = checker_content.replace("__VALIDATION__", io_contract["validation"])
    checker_content = checker_content.replace("__INPUT_PATTERN__", io_contract["input"])

    checker_path = plugin_dir / "glue" / "check_results.sh"
    checker_path.parent.mkdir(parents=True, exist_ok=True)
    checker_path.write_text(checker_content, encoding="utf-8")
    checker_path.chmod(checker_path.stat().st_mode | 0o755)

    # Verify syntax
    rc, out = _run_cmd(f"bash -n {checker_path}")
    if rc == 0:
        print(f"   ✅ check_results.sh generated ({checker_content.count(chr(10))} lines, template-based)")
    else:
        print(f"   ❌ Template syntax error (this shouldn't happen): {out[:200]}")

    # ══════════════════════════════════════════════════════════════════
    # Generate plugin.yaml if missing
    # ══════════════════════════════════════════════════════════════════
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.exists():
        plugin_name = plugin_dir.name
        manifest = {
            "name": plugin_name,
            "description": (scan.get("readme") or "")[:200].split("\n")[0],
            "scheduler": smoke.get("scheduler", "local"),
            "stages": [
                {"name": "compute", "description": "Run workflow",
                 "type": "command", "command": "bash glue/prepare_and_launch.sh"},
            ],
        }
        manifest_path.write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))
        print(f"\n📄 Generated plugin.yaml (name: {plugin_name})")

    # ══════════════════════════════════════════════════════════════════
    # Script generation summary
    # ══════════════════════════════════════════════════════════════════
    glue_out = plugin_dir / "glue"
    generated = []
    if glue_out.is_dir():
        generated = [f.name for f in glue_out.iterdir()
                     if f.is_file() and f.suffix in (".sh", ".py")]
    print(f"\n{'═' * 50}")
    print(f"📦 Scripts generated: {len(generated)} file(s)")
    for f in sorted(generated):
        fp = glue_out / f
        lines = fp.read_text().count("\n") if fp.exists() else 0
        print(f"   glue/{f} ({lines} lines)")

    if not generated:
        print("   ❌ No scripts generated. Cannot proceed to testing.")
        return {"status": "no_scripts"}

    # ── Prep-only mode: stop here ────────────────────────────────────
    if prep_only:
        workspace = plugin_dir / "workspace"
        _build_workspace(plugin_dir, workspace, test_input, real_xyz_files or None)
        print(f"\n✅ Workspace prepared: {workspace}")
        print(f"   To run manually:")
        print(f"   cd {workspace}")
        print(f"   bash glue/prepare_and_launch.sh")
        print(f"\n   Then resume with:")
        print(f"   python plugin.py develop {plugin_dir.name} --resume {workspace}")
        return {"status": "prepped", "workspace": str(workspace)}

    # ══════════════════════════════════════════════════════════════════
    # Phase 5-8: Pilot loop (workspace isolation, submit, wait, check)
    # ══════════════════════════════════════════════════════════════════
    max_iterations = 5

    print(f"\n{'═' * 50}")
    print(f"🧪 Starting pilot test loop (max {max_iterations} iterations)")
    print(f"{'═' * 50}")

    # Track active jobs for cleanup on interrupt
    _active_job_ids: List[str] = []

    def _cleanup_handler(signum, frame):
        if _active_job_ids:
            print(f"\n🧹 Cleaning up {len(_active_job_ids)} job(s)...")
            for jid in _active_job_ids:
                for cmd in ["qdel", "scancel", "condor_rm"]:
                    if shutil.which(cmd):
                        subprocess.call([cmd, jid],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            print("   Done.")
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGINT, _cleanup_handler)

    try:
        result = _run_pilot_loop(
            plugin_dir, log_dir, test_input, provider, model,
            max_iterations, poll_interval, smoke, generated, timestamp,
            _active_job_ids, real_xyz_files=real_xyz_files or None,
            max_wait=max_wait,
        )
    except KeyboardInterrupt:
        print("\n\n⚠  Interrupted by user.")
        result = {"status": "interrupted"}
    finally:
        signal.signal(signal.SIGINT, old_handler)

    return result


def _run_pilot_loop(
    plugin_dir: Path,
    log_dir: Path,
    test_input: Optional[Path],
    provider: str,
    model: str,
    max_iterations: int,
    poll_interval: int,
    smoke: Dict,
    generated: List[str],
    timestamp: str,
    active_job_ids: List[str],
    real_xyz_files: Optional[List[Path]] = None,
    max_wait: int = 7200,
) -> Dict[str, Any]:
    """The actual pilot loop, separated for signal handling."""

    for iteration in range(1, max_iterations + 1):
        print(f"\n══════════════════════════════════════════")
        print(f"  Iteration {iteration} / {max_iterations}")
        print(f"══════════════════════════════════════════")

        # ── Build fresh workspace ─────────────────────────────────────
        workspace = plugin_dir / "workspace"
        iter_log = log_dir / f"iteration_{iteration}"
        iter_log.mkdir(parents=True, exist_ok=True)

        _build_workspace(plugin_dir, workspace, test_input, real_xyz_files)

        # ── Find and run the glue entry script ────────────────────────
        launch_script = None
        glue_ws = workspace / "glue"
        if glue_ws.is_dir():
            # Try common names in priority order
            for name in ("prepare_and_launch.sh", "submit_all.sh", "run.sh", "launch.sh"):
                candidate = glue_ws / name
                if candidate.exists():
                    launch_script = candidate
                    break
            # Fallback: first .sh file in glue/
            if not launch_script:
                for f in sorted(glue_ws.iterdir()):
                    if f.suffix == ".sh" and f.name != "check_results.sh":
                        launch_script = f
                        break

        if not launch_script:
            print(f"\n   ❌ No launch script found in glue/")
            break

        launch_rel = launch_script.relative_to(workspace)
        print(f"\n🚀 Running {launch_rel}...")

        rc, launch_output = _run_cmd(
            f"bash {launch_rel}",
            cwd=str(workspace), timeout=600,
        )
        print(launch_output[-2000:] if len(launch_output) > 2000 else launch_output)

        # Save launch log
        (iter_log / "launch.log").write_text(launch_output)
        if rc != 0:
            (iter_log / "launch_error.log").write_text(
                f"LAUNCH FAILURE (exit code {rc})\n"
                f"Script: {launch_rel}\n"
                f"--- stdout+stderr ---\n{launch_output}\n"
            )
            print(f"\n⚠  Launch exited with code {rc}")

        # ── Track and wait for jobs ───────────────────────────────────
        job_ids = _extract_job_ids_from_output(launch_output)
        active_job_ids.clear()
        active_job_ids.extend(job_ids)

        # If launch failed and no jobs were submitted, skip result check
        # and go straight to diagnose — nothing could have succeeded.
        launch_failed = (rc != 0 and not job_ids)

        if rc == 0 and job_ids:
            print(f"\n⏳ Waiting for {len(job_ids)} job(s): {', '.join(job_ids)}")
            _wait_for_jobs(job_ids, poll_interval=poll_interval, timeout=max_wait)

        # ── Snapshot workspace ────────────────────────────────────────
        _snapshot_workspace(workspace, iter_log)

        # ── Check results ─────────────────────────────────────────────
        if launch_failed:
            print(f"\n❌ Launch failed with no jobs submitted — skipping result check.")
        else:
            check_script = workspace / "glue" / "check_results.sh"
            if check_script.exists():
                print(f"\n🔎 Checking results...")
                check_rc, check_output = _run_cmd(
                    f"bash glue/check_results.sh {workspace}",
                    cwd=str(workspace), timeout=60,
                )
                print(f"   {check_output}")

                if check_rc == 0:
                    # Verify this isn't a stub/fake success from auto-fix
                    stub = _detect_stub_success(workspace, launch_output)
                    if stub:
                        print(f"\n⚠  Checker passed but output is a stub: {stub}")
                        print(f"   Auto-fix created a skip/fake path — not a real pass.")
                        print(f"   Proceeding to diagnose.")
                    else:
                        print(f"\n🎉 Pilot PASSED on iteration {iteration}!")
                        print(f"   {check_output}")
                        (iter_log / "check_passed.json").write_text(
                            json.dumps({"status": "passed", "iteration": iteration,
                                        "output": check_output})
                        )
                        _save_dev_log(log_dir, timestamp, plugin_dir, provider, model,
                                      smoke, generated, test_input, iteration, "passed")
                        return {"status": "passed", "iteration": iteration}
                else:
                    print(f"   ⚠  check_results exited {check_rc} — proceeding to diagnose")

        # ── Diagnose + auto-fix ───────────────────────────────────────
        print(f"\n🔍 Running diagnose + auto-fix...")

        # Link persistent glue into snapshot so fixes write to the right place
        glue_link = iter_log / "glue"
        if not glue_link.exists():
            try:
                glue_link.symlink_to(plugin_dir / "glue")
            except OSError:
                pass

        try:
            from .diagnose import diagnose_results
            diag_result = diagnose_results(
                pilot_dir=iter_log,
                provider=provider,
                model=model,
                mode="pilot",
                auto_fix=True,
            )
        except Exception as e:
            logger.error("Auto-diagnose failed: %s", e)
            print(f"   ❌ Diagnose error: {e}")
            diag_result = {"error": str(e)}

        # Save diagnose output
        (iter_log / "diagnose_result.json").write_text(
            json.dumps(diag_result, indent=2, default=str)
        )

        # ── Check: no more fixes possible? ────────────────────────────
        if isinstance(diag_result, dict):
            if diag_result.get("status") == "all_passed":
                print(f"\n🎉 Pilot PASSED on iteration {iteration}!")
                _save_dev_log(log_dir, timestamp, plugin_dir, provider, model,
                              smoke, generated, test_input, iteration, "passed")
                return {"status": "passed", "iteration": iteration}

            fixes = diag_result.get("fixes", {})
            if isinstance(fixes, dict) and not fixes.get("fixes_applied"):
                if fixes.get("skips"):
                    print(f"\n⚠  No more glue fixes possible. Remaining issues need human judgment.")
                    _save_dev_log(log_dir, timestamp, plugin_dir, provider, model,
                                  smoke, generated, test_input, iteration, "needs_human")
                    return {"status": "needs_human", "iteration": iteration}

        if iteration < max_iterations:
            print(f"   Fixes applied. Continuing to iteration {iteration + 1}...")
            time.sleep(3)

    print(f"\n❌ Max iterations ({max_iterations}) reached.")
    print(f"   Review logs: {log_dir}")
    _save_dev_log(log_dir, timestamp, plugin_dir, provider, model,
                  smoke, generated, test_input, max_iterations, "max_iterations")
    return {"status": "max_iterations", "dev_log": str(log_dir)}
