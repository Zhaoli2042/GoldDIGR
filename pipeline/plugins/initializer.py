"""
pipeline.plugins.initializer – LLM-powered plugin scaffold generator.

Reads the user's scripts and README, learns from a reference plugin, and
asks an LLM to generate:
  1. plugin.yaml  — machine-readable workflow manifest
  2. glue/*       — thin adapter scripts that connect golddigr XYZ output
                    to the user's EXISTING workflow scripts

KEY DESIGN PRINCIPLE: The LLM never rewrites, stubs, or recreates the
user's scripts.  Glue is a DATA FORMAT ADAPTER that calls the user's code.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .registry import validate_plugin, load_manifest
from ._utils import call_llm, ask_user, confirm, parse_multi_file_output, fix_yaml_quoting

logger = logging.getLogger(__name__)

_MAX_SCRIPT_CHARS = 15_000
_MAX_PROMPT_CHARS = 120_000


# ═══════════════════════════════════════════════════════════════════════
# File scanning
# ═══════════════════════════════════════════════════════════════════════

def _scan_plugin_dir(plugin_dir: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"readme": None, "environment": None, "scripts": [], "templates": []}
    _SCRIPT_EXTS = (".py", ".sh", ".bash", ".r", ".R", ".submit")

    try:
        from .ignore import load_ignore_patterns, should_ignore
        ig_patterns = load_ignore_patterns(plugin_dir)
    except ImportError:
        ig_patterns = []

    for name in ("README.md", "WORKFLOW.md", "README.txt", "README"):
        rp = plugin_dir / name
        if rp.exists():
            content = rp.read_text(errors="ignore")[:_MAX_SCRIPT_CHARS]
            if info["readme"]:
                info["readme"] += f"\n\n--- {name} ---\n{content}"
            else:
                info["readme"] = content

    for name in ("environment.yml", "environment.yaml", "conda.yml"):
        ep = plugin_dir / name
        if ep.exists():
            info["environment"] = ep.read_text(errors="ignore")[:5000]
            break

    # Scan scripts/ directory and root; also scan all subdirs for deeper layouts
    scripts_dir = plugin_dir / "scripts"
    if scripts_dir.is_dir():
        for sf in sorted(scripts_dir.rglob("*")):
            if sf.is_file() and sf.suffix in _SCRIPT_EXTS:
                if ig_patterns and should_ignore(sf, plugin_dir, ig_patterns):
                    continue
                content = sf.read_text(errors="ignore")[:_MAX_SCRIPT_CHARS]
                info["scripts"].append({
                    "path": str(sf.relative_to(plugin_dir)),
                    "name": sf.name, "content": content,
                })

    # Also scan plugin root and all subdirs (for non-standard layouts like MD/)
    for sf in sorted(plugin_dir.rglob("*")):
        if sf.is_file() and sf.suffix in _SCRIPT_EXTS:
            if ig_patterns and should_ignore(sf, plugin_dir, ig_patterns):
                continue
            if not any(s["name"] == sf.name for s in info["scripts"]):
                content = sf.read_text(errors="ignore")[:_MAX_SCRIPT_CHARS]
                info["scripts"].append({
                    "path": str(sf.relative_to(plugin_dir)),
                    "name": sf.name, "content": content,
                })

    templates_dir = plugin_dir / "templates"
    if templates_dir.is_dir():
        for tf in sorted(templates_dir.rglob("*")):
            if tf.is_file():
                if ig_patterns and should_ignore(tf, plugin_dir, ig_patterns):
                    continue
                content = tf.read_text(errors="ignore")[:5000]
                info["templates"].append({
                    "path": str(tf.relative_to(plugin_dir)),
                    "name": tf.name, "content": content,
                })

    return info


def _extract_script_summary(script: Dict) -> str:
    """Extract a 1-2 line summary from a script's header comments."""
    lines = script["content"].split("\n")
    summary_lines = []
    for line in lines[:20]:
        stripped = line.strip().lstrip("#").strip()
        if stripped and not stripped.startswith("!"):
            summary_lines.append(stripped)
        if len(summary_lines) >= 2:
            break
    return " ".join(summary_lines) if summary_lines else "(no description)"


def _identify_entry_point(scan: Dict) -> Optional[Dict]:
    """Identify the most likely entry-point script."""
    # Priority: start.sh > main.sh > run.sh > first .sh
    for name in ("start.sh", "main.sh", "run.sh", "launch.sh"):
        for s in scan["scripts"]:
            if s["name"] == name:
                return s
    # Fallback: the script that calls other scripts
    for s in scan["scripts"]:
        content = s["content"]
        call_count = sum(1 for other in scan["scripts"]
                         if other["name"] != s["name"]
                         and other["name"] in content)
        if call_count >= 2:
            return s
    return scan["scripts"][0] if scan["scripts"] else None


def _identify_driver_script(scan: Dict) -> Optional[Dict]:
    """Identify the script that runs the actual computation (called per-job)."""
    for name in ("run_orca_wbo.sh", "run.sh", "runner.sh"):
        for s in scan["scripts"]:
            if s["name"] == name:
                return s
    # Look for the script referenced in .submit files
    for s in scan["scripts"]:
        if s["name"].endswith(".submit"):
            for other in scan["scripts"]:
                if other["name"] != s["name"] and other["name"] in s["content"]:
                    return other
    return None


def _load_reference_plugin(plugins_root: Path) -> Optional[Dict[str, str]]:
    ref_dir = plugins_root / "xtb-freq-tsopt-irc-wbo"
    if not ref_dir.is_dir():
        for d in plugins_root.iterdir():
            if d.is_dir() and (d / "plugin.yaml").exists():
                ref_dir = d
                break
        else:
            return None

    result = {}
    for fname in ("plugin.yaml",):
        fp = ref_dir / fname
        if fp.exists():
            result[fname] = fp.read_text(errors="ignore")

    glue_dir = ref_dir / "glue"
    if glue_dir.is_dir():
        for gf in sorted(glue_dir.iterdir()):
            if gf.is_file():
                result[f"glue/{gf.name}"] = gf.read_text(errors="ignore")

    return result if result else None


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: Clarifying questions
# ═══════════════════════════════════════════════════════════════════════

_QUESTIONS_SYSTEM = """\
You are analyzing a user's computational scripts to write a thin adapter \
("glue") that connects golddigr's output to the user's existing scripts.

golddigr extracts individual .xyz files from chemistry papers.  The user's \
scripts may expect a different input format (zip archives, specific directory \
structures, filenames encoding charge/multiplicity).

Generate 2-4 targeted questions.  ONLY ask about things you genuinely \
CANNOT determine from the code.

DO NOT ask about:
- Resource limits, memory, CPUs (visible in the scripts)
- What scheduler is used (visible: condor_submit vs sbatch)
- What the scripts do (you can read them)

GOOD questions (things NOT in the code):
- "golddigr extracts bare .xyz files (block_01.xyz, block_02.xyz). Your \
scripts expect XX_charge_mult.zip. Should I sample charges [-1, 0, 1] or \
is charge always 0?"
- "Should the glue create one tar.gz per article, or one big tar.gz?"
- "Is the Singularity container already at the OSDF path in your scripts?"

Output a JSON array of question strings.  Nothing else.
"""


def _generate_questions(provider, model, scan, reference):
    parts = []
    if scan["readme"]:
        parts.append(f"=== README ===\n{scan['readme']}\n=== END ===\n")
    # Only send script summaries for questions phase — not full content
    parts.append("=== USER'S SCRIPTS (summaries) ===")
    for s in scan["scripts"]:
        summary = _extract_script_summary(s)
        parts.append(f"  {s['name']}: {summary}")
    parts.append("=== END ===\n")
    # Send the driver script in full so the LLM can see the input format
    driver = _identify_driver_script(scan)
    if driver:
        parts.append(f"=== DRIVER SCRIPT (runs per-job): {driver['name']} ===\n"
                      f"{driver['content'][:8000]}\n=== END ===\n")
    prompt = "\n".join(parts)
    if len(prompt) > _MAX_PROMPT_CHARS:
        prompt = prompt[:_MAX_PROMPT_CHARS]

    raw = call_llm(provider, model, _QUESTIONS_SYSTEM, prompt, 0.3, timeout=180)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    try:
        questions = json.loads(raw)
        if isinstance(questions, list):
            return [str(q) for q in questions]
    except json.JSONDecodeError:
        return [l.strip().lstrip("- ").strip('"') for l in raw.splitlines() if l.strip()]
    return []


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: Generate plugin.yaml
# ═══════════════════════════════════════════════════════════════════════

_MANIFEST_SYSTEM = """\
You are a build engineer for golddigr — a pipeline that scrapes chemistry \
papers, extracts XYZ coordinate files, and then packages them for user-defined \
computational workflows on HPC clusters.

Generate a plugin.yaml manifest that describes the user's workflow.  This file \
is metadata/documentation — it does NOT control execution directly.

RULES:
- name: short slug for the plugin
- description: one-line summary
- scheduler: slurm | htcondor | local
- stages: list of {name, description, type, gate}
  - type: command | python | container
  - gate: {type: file_exists|directory_exists|imaginary_freq, file: ..., threshold: ...}
- charge_strategy: how to determine charge/mult
- outputs: what files to collect

YAML FORMATTING — CRITICAL:
- ALL string values that contain colons (:), curly braces, square brackets, \
  or special characters MUST be wrapped in double quotes.
  WRONG:  description: count electrons: if even -> mult=1
  RIGHT:  description: "count electrons: if even -> mult=1"
- When in doubt, quote the string. Unquoted colons break YAML parsing.
- Multi-line descriptions should use the > (folded) or | (literal) block scalar.

Output ONLY raw YAML.  No markdown fences, no explanation.
"""


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: Generate glue scripts
# ═══════════════════════════════════════════════════════════════════════

_GENERATE_SYSTEM = """\
You are a build engineer for golddigr — a pipeline that extracts molecular \
geometries (.xyz files) from chemistry papers and packages them for HPC workflows.

You will be told the BUILD MODE, which determines what you generate:

══════════════════════════════════════════════════════════════════════════════
MODE: full_build
  The user provided only a README (and maybe sample files).
  Generate the ENTIRE workflow: driver script, submission scripts, monitors.
  Use the SNIPPET LIBRARY heavily — assemble from tested building blocks.
  Generate 3-8 files under glue/ (driver, submission, wrapper, monitors).

MODE: build_around
  The user provided 1-3 scripts (their core science/analysis).
  Generate everything ELSE: submission, task wrapper, monitoring, adapters.
  Do NOT rewrite the user's existing scripts.
  Generate 2-5 files under glue/.

MODE: glue_only
  The user provided a full workflow (many scripts).
  Generate ONLY a thin adapter that bridges golddigr's xyz/ output to
  the user's entry-point script.
  Do NOT rewrite any existing scripts.
  Generate 1-2 files under glue/.
══════════════════════════════════════════════════════════════════════════════

GOLDDIGR OUTPUT FORMAT:
  xyz/block_01.xyz    — individual .xyz files, one per molecular structure
  xyz/block_02.xyz    — standard XYZ: line 1 = natoms, line 2 = comment,
                        remaining lines = element x y z

MANDATORY IN EVERY GENERATED BASH SCRIPT:
  After set -euo pipefail, always add this ERR trap:
    trap 'echo "GLUE ERROR at ${{BASH_SOURCE}}:$LINENO (exit=$?): $(sed -n ${LINENO}p "${{BASH_SOURCE[0]}}" 2>/dev/null)" >&2' ERR
  This ensures failures produce diagnosable error messages instead of silent exits.

CHARGE AND MULTIPLICITY:
  total_electrons = sum(atomic_numbers) - charge
  if total_electrons is even → mult = 1 (singlet)
  if total_electrons is odd  → mult = 2 (doublet)
Use Python for this computation. NEVER brute-force enumerate {1,2,3,...}.

SNIPPET LIBRARY:
If snippets from the library are provided, PREFER using them over \
generating from scratch. To use a snippet:
1. Copy its code structure
2. Replace {{PLACEHOLDER}} variables with actual values
3. PRESERVE invariants exactly — they encode hard-won lessons
4. Add a comment noting which concept was used

FILE NAMING:
- All generated files go under glue/ (e.g., glue/prepare_and_launch.sh)
- In build_around and glue_only modes: NEVER generate a file with the \
  same name as an existing user script
- In full_build mode: generate whatever files are needed

MANDATORY FILE — glue/check_results.sh:
You MUST ALWAYS generate glue/check_results.sh in EVERY build mode. \
This script defines what "success" means for this specific workflow. \
The pilot loop calls it after jobs finish to decide pass/fail.

CONTRACT:
  - Takes one argument: $1 = workspace directory path
  - Exits 0 if the workflow succeeded (all expected outputs present and valid)
  - Exits 1 if the workflow failed or is incomplete
  - Prints a one-line summary to stdout (e.g., "Results: 3/3 passed")
  - Must be self-contained (no external dependencies beyond standard tools + python3)

The check logic is WORKFLOW-SPECIFIC. Examples:
  - ORCA workflow: look for *_results.tar.gz in results/, unpack, check status.json
  - MD simulation: check if stability.out exists and has data
  - xTB scan: count output CSV files vs expected count
  - ML training: check if model checkpoint and metrics file exist

TEMPLATE:
  #!/bin/bash
  set -euo pipefail
  WORKSPACE="${1:-.}"
  PASSED=0; FAILED=0; TOTAL=0
  # ... workflow-specific checks ...
  echo "Results: $PASSED/$TOTAL passed, $FAILED failed"
  [ "$PASSED" -gt 0 ] && [ "$FAILED" -eq 0 ] && exit 0
  exit 1

OUTPUT FORMAT:
=== FILE: glue/prepare_and_launch.sh ===
#!/bin/bash
...script content...

=== FILE: glue/task_wrapper.sh ===
#!/bin/bash
...script content...

No markdown fences. No explanation outside the files.
"""


def _build_prompt(scan, reference, user_answers, extra_context=""):
    """Build the user prompt for manifest generation (full scripts included)."""
    parts = []

    if reference:
        parts.append("=== REFERENCE PLUGIN (working example) ===")
        for fname, content in reference.items():
            parts.append(f"--- {fname} ---\n{content}")
        parts.append("=== END REFERENCE ===\n")

    if scan["readme"]:
        parts.append(f"=== USER'S README ===\n{scan['readme']}\n=== END ===\n")

    for script in scan["scripts"]:
        parts.append(f"=== SCRIPT: {script['path']} ===\n{script['content']}\n=== END ===\n")

    for template in scan["templates"]:
        parts.append(f"=== TEMPLATE: {template['path']} ===\n{template['content']}\n=== END ===\n")

    if scan["environment"]:
        parts.append(f"=== ENVIRONMENT ===\n{scan['environment'][:3000]}\n=== END ===\n")

    if user_answers:
        parts.append("=== USER'S ANSWERS ===")
        for q, a in user_answers.items():
            parts.append(f"Q: {q}\nA: {a}")
        parts.append("=== END ANSWERS ===\n")

    if extra_context:
        parts.append(extra_context)

    prompt = "\n".join(parts)
    if len(prompt) > _MAX_PROMPT_CHARS:
        prompt = prompt[:_MAX_PROMPT_CHARS] + "\n... (truncated)"
    return prompt


def _build_generate_prompt(scan, user_answers, yaml_text, catalog_context="",
                           build_mode="glue_only"):
    """Build a mode-adaptive prompt for workflow generation.

    BUILD MODES:
      full_build:   README only → generate entire workflow from library
      build_around: 1-3 scripts → generate everything else around them
      glue_only:    full workflow → generate thin adapter only
    """
    parts = [f"BUILD MODE: {build_mode}\n"]

    # README in full
    if scan["readme"]:
        parts.append(f"=== USER'S README ===\n{scan['readme']}\n=== END ===\n")

    if build_mode == "full_build":
        # ── Full build: README describes what to build ────────────────
        parts.append(
            "The user has NO existing scripts. Build the entire workflow from\n"
            "the README description and the snippet library.\n\n"
            "Generate all needed files under glue/:\n"
            "  - glue/prepare_and_launch.sh (main entry: data prep + submission)\n"
            "  - glue/run_driver.sh (per-job science execution)\n"
            "  - glue/task_wrapper.sh (scheduler-specific job wrapper)\n"
            "  - Additional scripts as needed (monitors, status, etc.)\n"
        )

        # Include sample files (crucial for full_build — only way to see format)
        if scan["templates"]:
            parts.append("=== TEMPLATES ===")
            for t in scan["templates"]:
                parts.append(f"  {t['name']}:\n{t['content'][:3000]}")
            parts.append("=== END TEMPLATES ===\n")

    elif build_mode == "build_around":
        # ── Build around: user has 1-3 core scripts ───────────────────
        parts.append("=== USER'S SCRIPTS (the core — DO NOT REWRITE) ===")
        for s in scan["scripts"]:
            parts.append(f"\n--- {s['path']} ({s['content'].count(chr(10))} lines) ---")
            parts.append(s["content"][:_MAX_SCRIPT_CHARS])
        parts.append("=== END USER SCRIPTS ===\n")

        parts.append(
            "The user provided the core science/analysis script(s) above.\n"
            "Build everything ELSE around them: submission, task wrapper,\n"
            "monitoring, data adapter. DO NOT rewrite the user's scripts.\n\n"
            "Generate files under glue/:\n"
            "  - glue/prepare_and_launch.sh (data prep + submission)\n"
            "  - glue/task_wrapper.sh (per-job wrapper that CALLS the user's script)\n"
            "  - Additional scripts as needed\n"
        )

    else:
        # ── Glue only: user has a full workflow ───────────────────────
        script_names = [s["name"] for s in scan["scripts"]]

        parts.append("=== USER'S EXISTING SCRIPTS (DO NOT REGENERATE) ===")
        for s in scan["scripts"]:
            summary = _extract_script_summary(s)
            lines = s["content"].count("\n")
            parts.append(f"  {s['name']} ({lines} lines): {summary}")
        parts.append("=== END SCRIPT LIST ===\n")

        parts.append("=== FORBIDDEN: DO NOT GENERATE FILES WITH THESE NAMES ===")
        for name in script_names:
            parts.append(f"  ❌ {name}")
        parts.append("=== END FORBIDDEN LIST ===\n")

        # Entry-point script
        entry = _identify_entry_point(scan)
        if entry:
            parts.append(f"=== ENTRY-POINT SCRIPT: {entry['name']} ===")
            parts.append(f"Your glue should CALL this script (not rewrite it).")
            parts.append(f"First 80 lines:\n{chr(10).join(entry['content'].split(chr(10))[:80])}")
            parts.append(f"=== END ENTRY-POINT ===\n")

        # Driver script in full
        driver = _identify_driver_script(scan)
        if driver and driver["name"] != (entry["name"] if entry else ""):
            parts.append(f"=== DRIVER SCRIPT (per-job): {driver['name']} ===")
            parts.append(f"Read CAREFULLY to understand the expected input format:")
            parts.append(f"  - Filename pattern, charge/mult encoding")
            parts.append(f"  - Expected files inside zip/archive")
            parts.append(f"\n{chr(10).join(driver['content'].split(chr(10))[:200])}")
            parts.append(f"=== END DRIVER ===\n")

        # Submit file
        for s in scan["scripts"]:
            if s["name"].endswith(".submit"):
                parts.append(f"=== SUBMIT FILE: {s['name']} ===\n{s['content']}\n=== END ===\n")

        entry_name = entry["name"] if entry else "start.sh"
        parts.append(
            f"Generate ONE glue script (glue/prepare_and_launch.sh) that:\n"
            f"  1. Reads xyz/*.xyz files from golddigr's output\n"
            f"  2. Transforms them into the format the entry-point expects\n"
            f"  3. Calls the user's entry-point: {entry_name}\n"
            f"Do NOT generate any other scripts.\n"
        )

    # Generated manifest
    parts.append(f"=== GENERATED plugin.yaml ===\n{yaml_text}\n=== END ===\n")

    # User answers
    if user_answers:
        parts.append("=== USER'S ANSWERS ===")
        for q, a in user_answers.items():
            parts.append(f"Q: {q}\nA: {a}")
        parts.append("=== END ANSWERS ===\n")

    # Catalog + library + samples + containers context
    if catalog_context:
        parts.append(catalog_context)
        parts.append(
            "Use the snippet library and catalog to assemble tested code blocks.\n"
            "Preserve invariants. Adapt to the target scheduler from the probe.\n"
        )

    prompt = "\n".join(parts)
    if len(prompt) > _MAX_PROMPT_CHARS:
        prompt = prompt[:_MAX_PROMPT_CHARS] + "\n... (truncated)"
    return prompt



def _validate_glue_output(glue_files: Dict[str, str], scan: Dict) -> List[str]:
    """
    Post-generation validation.  Returns list of problems found.
    Catches the LLM rewriting user scripts.
    """
    problems = []
    user_script_names = {s["name"] for s in scan["scripts"]}
    user_script_names_lower = {n.lower() for n in user_script_names}

    for fname, content in glue_files.items():
        clean_name = fname.replace("glue/", "").strip("/")

        # Check 1: Does the glue file share a name with a user script?
        if clean_name in user_script_names:
            problems.append(
                f"REJECTED: '{clean_name}' has the same name as a user script. "
                f"Glue must not replace user scripts."
            )
        elif clean_name.lower() in user_script_names_lower:
            problems.append(
                f"REJECTED: '{clean_name}' matches a user script (case-insensitive)."
            )

        # Check 2: Does it look like a rewrite? (contains scheduler commands
        # but doesn't call any user script)
        calls_user_script = any(
            sname in content for sname in user_script_names
        )
        has_scheduler = ("condor_submit" in content or "sbatch" in content
                         or "condor_q" in content or "squeue" in content)

        if has_scheduler and not calls_user_script:
            problems.append(
                f"WARNING: '{clean_name}' contains scheduler commands but doesn't "
                f"call any user script. This looks like a rewrite, not glue."
            )

    # Check 3: Too many files generated
    if len(glue_files) > 3:
        problems.append(
            f"WARNING: {len(glue_files)} glue files generated. "
            f"Expected 1-2. The LLM may be rewriting user scripts."
        )

    # Check 4: Brute-force multiplicity enumeration
    for fname, content in glue_files.items():
        if re.search(r'for\s+\w+\s+in\s+\{1\.\.\d\}', content):
            problems.append(
                f"WARNING: '{fname.replace('glue/', '')}' uses brute-force multiplicity "
                f"enumeration ({{1..N}}). Multiplicity must be computed from electron "
                f"count, not enumerated."
            )
        if re.search(r'for\s+MULT\s+in\s+1\s+2\s+3', content):
            problems.append(
                f"WARNING: '{fname.replace('glue/', '')}' enumerates MULT values. "
                f"Multiplicity must be computed from electron count."
            )

    return problems


def _validate_yaml(yaml_text: str) -> Tuple[bool, str]:
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return False, f"Invalid YAML: {e}"
    if not isinstance(data, dict):
        return False, "Top-level must be a YAML mapping"
    if "name" not in data:
        return False, "Missing 'name'"
    return True, "OK"


def _extract_yaml(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()




# ═══════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════

def init_plugin(
    plugin_dir: Path,
    plugins_root: Path,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    non_interactive: bool = False,
) -> bool:
    """
    LLM-powered plugin initialization.

    1. Scans plugin directory
    2. Generates clarifying questions → user answers
    3. Generates plugin.yaml
    4. Generates glue script (thin adapter ONLY)
    5. Validates glue didn't rewrite user scripts
    6. Writes after user confirmation

    Returns True if files were written successfully.
    """
    plugin_dir = Path(plugin_dir).resolve()
    print(f"\n🔍 Scanning plugin directory: {plugin_dir}\n")

    # ── Scan ──────────────────────────────────────────────────────────
    scan = _scan_plugin_dir(plugin_dir)

    # ── Detect build mode from what's present ─────────────────────────
    n_scripts = len(scan["scripts"])
    has_readme = bool(scan["readme"])
    has_driver = bool(_identify_driver_script(scan))
    has_entry = bool(_identify_entry_point(scan))
    has_submission = any(
        any(kw in s.get("content", "").lower()
            for kw in ("qsub", "sbatch", "condor_submit"))
        for s in scan["scripts"]
    )
    has_monitor = any(
        any(kw in s.get("content", "").lower()
            for kw in ("health", "monitor", "auto-heal", "autoheal"))
        for s in scan["scripts"]
    )

    if n_scripts == 0:
        build_mode = "full_build"
    elif n_scripts <= 3 and not has_submission:
        build_mode = "build_around"
    else:
        build_mode = "glue_only"

    mode_labels = {
        "full_build": "📦 Build entire workflow from library + README",
        "build_around": "🔧 Build workflow around your script(s)",
        "glue_only": "🔌 Generate glue for existing scripts",
    }
    print(f"  Mode: {mode_labels[build_mode]}")
    print(f"  Found: {n_scripts} scripts, "
          f"{len(scan['templates'])} templates, "
          f"README: {'yes' if has_readme else 'no'}, "
          f"environment: {'yes' if scan['environment'] else 'no'}")

    entry = _identify_entry_point(scan)
    driver = _identify_driver_script(scan)
    if entry:
        print(f"  Entry point: {entry['name']}")
    if driver:
        print(f"  Driver (per-job): {driver['name']}")

    if not has_readme:
        print("\n⚠  No README.md found. The LLM works much better with a README.")
        if build_mode == "full_build":
            print("   In full-build mode, a README is essential — it describes what to build.")
            if not non_interactive and not confirm("Continue without README?"):
                return False
        elif not non_interactive and not confirm("Continue without README?"):
            return False

    reference = _load_reference_plugin(plugins_root)
    if reference:
        print(f"  📚 Loaded reference plugin ({len(reference)} files)")

    # Load catalog for cross-referencing patterns
    catalog_context = ""
    try:
        from .catalog import load_catalog
        catalog = load_catalog(plugins_root)
        cat_plugins = catalog.get("plugins", {})
        if cat_plugins:
            catalog_context = f"=== CATALOG: {len(cat_plugins)} known plugin(s) ===\n"
            catalog_context += yaml.dump(cat_plugins, default_flow_style=False,
                                         sort_keys=False, width=120)
            catalog_context += "=== END CATALOG ===\n"
            print(f"  📖 Loaded catalog ({len(cat_plugins)} entries)")
    except Exception:
        pass

    # Probe target infrastructure
    infra_context = ""
    try:
        from .probe import probe_infrastructure, format_probe_report, format_probe_for_prompt
        infra = probe_infrastructure()
        print(format_probe_report(infra))
        print()
        infra_context = format_probe_for_prompt(infra)
        # Append to catalog context so it's included in all prompts
        catalog_context = infra_context + "\n" + catalog_context
    except Exception:
        pass

    # ── Phase 1: Clarifying questions ─────────────────────────────────
    print(f"\n🤖 Asking {provider}/{model} to analyze your scripts...\n")

    try:
        questions = _generate_questions(provider, model, scan, reference)
    except Exception as e:
        logger.error("LLM API error during question generation: %s", e)
        print(f"❌ LLM API error: {e}")
        return False

    user_answers = {}
    if questions and not non_interactive:
        print("📋 A few questions to help generate your plugin:\n")
        for i, q in enumerate(questions, 1):
            answer = ask_user(f"{i}. {q}")
            if answer:
                user_answers[q] = answer
        print()

    # ── Phase 2: Generate plugin.yaml ─────────────────────────────────
    print("🔧 Generating plugin.yaml...\n")

    manifest_prompt = _build_prompt(scan, reference, user_answers,
                                    catalog_context +
                                    "\nGenerate a plugin.yaml for this workflow.\n"
                                    "If the catalog contains similar plugins, learn from their "
                                    "patterns but adapt to this specific workflow.\n"
                                    "Output ONLY raw YAML, no fences.\n")
    try:
        raw_manifest = call_llm(provider, model, _MANIFEST_SYSTEM, manifest_prompt, temperature, timeout=180)
    except Exception as e:
        logger.error("LLM API error during manifest generation: %s", e)
        print(f"❌ LLM API error: {e}")
        return False

    yaml_text = _extract_yaml(raw_manifest)
    valid, msg = _validate_yaml(yaml_text)
    if not valid:
        # Try programmatic fix first: quote unquoted values containing colons
        yaml_text = fix_yaml_quoting(yaml_text)
        valid, msg = _validate_yaml(yaml_text)

    if not valid:
        print(f"⚠  plugin.yaml issue: {msg}")
        if non_interactive:
            return False
        if confirm("Try to regenerate?"):
            fix_prompt = (
                    f"Your YAML has a parsing error: {msg}\n\n"
                    f"COMMON CAUSE: Unquoted strings containing colons.\n"
                    f"WRONG:  description: count electrons: if even -> 1\n"
                    f"RIGHT:  description: \"count electrons: if even -> 1\"\n\n"
                    f"Fix ALL strings that contain colons by wrapping them in double quotes.\n"
                    f"Output ONLY the corrected YAML, no explanation.\n\n"
                    f"Broken YAML:\n{yaml_text}"
                )
            try:
                raw_manifest = call_llm(provider, model, _MANIFEST_SYSTEM, fix_prompt, temperature, timeout=180)
                yaml_text = _extract_yaml(raw_manifest)
                valid, msg = _validate_yaml(yaml_text)
                if not valid:
                    print(f"❌ Still invalid: {msg}")
                    return False
            except Exception as e:
                logger.error("LLM retry failed during manifest regeneration: %s", e)
                print(f"❌ Retry failed: {e}")
                return False
        else:
            return False

    parsed_manifest = yaml.safe_load(yaml_text)

    # Show manifest summary
    stages = parsed_manifest.get("stages", [])
    print("═" * 60)
    print(f"  Plugin: {parsed_manifest.get('name', '?')}")
    print(f"  Scheduler: {parsed_manifest.get('scheduler', '?')}")
    print(f"  Stages: {len(stages)}")
    print("─" * 60)
    for i, s in enumerate(stages, 1):
        gate = s.get("gate", {})
        gate_str = f" → gate: {gate.get('type', '')} {gate.get('file', gate.get('threshold', ''))}" if gate else ""
        print(f"  {i}. {s.get('name', '?'):<20s} ({s.get('type', '?')}){gate_str}")
    print("═" * 60)

    if not non_interactive:
        print(f"\n📄 Full plugin.yaml:\n")
        print(yaml_text)
        print()
        if not confirm("Accept this plugin.yaml?"):
            return False

    # ── Phase 3: Generate glue script ─────────────────────────────────
    print("\n🔧 Generating glue script...\n")

    # Load relevant concepts from library
    snippet_context = ""
    try:
        from .library import find_concepts_for_workflow, format_concepts_for_prompt

        # Determine target scheduler from probe
        target_sched = None
        shared_fs = None
        try:
            from .probe import load_saved_probe
            saved_probe = load_saved_probe()
            if saved_probe:
                sched_list = saved_probe.get("schedulers_available",
                             [saved_probe.get("scheduler", "")])
                if isinstance(sched_list, list) and sched_list:
                    target_sched = sched_list[0]
                elif isinstance(sched_list, str):
                    target_sched = sched_list.split(",")[0]

                fs = saved_probe.get("filesystem", {})
                if isinstance(fs, dict):
                    shared_fs = bool(fs.get("shared", fs.get("shared_filesystem", False)))
        except Exception:
            pass

        # Detect tools from scripts
        script_text = " ".join(s.get("content", "")[:500] for s in scan["scripts"])
        tools = []
        for tool in ("orca", "gaussian", "multiwfn", "xtb", "pytorch", "tensorflow"):
            if tool in script_text.lower():
                tools.append(tool)

        # Find all relevant concepts with best variant for target infrastructure
        concepts = find_concepts_for_workflow(
            plugins_root,
            scheduler=target_sched,
            shared_fs=shared_fs,
            tools=tools or None,
        )

        if concepts:
            snippet_context = format_concepts_for_prompt(
                concepts, include_code=True
            )
            print(f"   📦 Loaded {len(concepts)} concept(s) from library")
            for c in concepts:
                best = c.get("best_variant", {})
                print(f"      {c['concept']}: variant={best.get('variant_name', '?')} "
                      f"(score={best.get('score', 0)})")

    except Exception as e:
        logger.debug("Concept loading failed: %s", e)

    # Load sample files from the plugin directory
    sample_context = ""
    try:
        from .samples import detect_samples, inspect_sample, format_samples_for_prompt
        detected = detect_samples(plugin_dir)
        if detected:
            inspected = []
            for s in detected:
                filepath = Path(s["path"])
                if filepath.exists():
                    info = inspect_sample(filepath)
                    info["relative"] = s["relative"]
                    inspected.append(info)
            if inspected:
                sample_context = format_samples_for_prompt(inspected)
                print(f"   📄 Loaded {len(inspected)} sample file(s)")
    except Exception as e:
        logger.debug("Sample loading failed: %s", e)

    # Detect container interfaces
    container_context = ""
    try:
        from .containers import detect_container_usage, format_containers_for_prompt
        # Also check if containers.yaml already exists
        from .containers import load_containers_yaml
        existing = load_containers_yaml(plugin_dir)
        if existing.get("containers"):
            container_context = "=== CONTAINER INTERFACES (from containers.yaml) ===\n"
            container_context += yaml.dump(existing, default_flow_style=False)
            container_context += "=== END ===\n"
            print(f"   🐳 Loaded {len(existing['containers'])} container interface(s) from containers.yaml")
        else:
            detections = detect_container_usage(plugin_dir)
            if detections:
                container_context = format_containers_for_prompt(detections)
                print(f"   🐳 Detected {len(detections)} container invocation(s) in scripts")
    except Exception as e:
        logger.debug("Container detection failed: %s", e)

    # Combine all context
    full_context = catalog_context
    if snippet_context:
        full_context = snippet_context + "\n" + full_context
    if sample_context:
        full_context = sample_context + "\n" + full_context
    if container_context:
        full_context = container_context + "\n" + full_context

    glue_prompt = _build_generate_prompt(scan, user_answers, yaml_text, full_context,
                                          build_mode=build_mode)

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            raw_glue = call_llm(provider, model, _GENERATE_SYSTEM, glue_prompt, temperature, timeout=180)
        except Exception as e:
            logger.error("LLM API error during glue generation: %s", e)
            print(f"❌ LLM API error: {e}")
            return False

        glue_files = parse_multi_file_output(raw_glue)

        if not glue_files:
            print("⚠  No scripts generated.")
            if not non_interactive and confirm("Continue without generated scripts?"):
                glue_files = {}
                break
            else:
                return False

        # ── Validate based on build mode ─────────────────────────────
        if build_mode == "full_build":
            # In full_build: no existing scripts to protect, just check quality
            print(f"\n📄 Generated {len(glue_files)} file(s):")
            for fname, content in glue_files.items():
                lines = content.count("\n")
                print(f"   {fname} ({lines} lines)")
            break

        elif build_mode == "build_around":
            # In build_around: check we didn't overwrite the user's scripts
            problems = _validate_glue_output(glue_files, scan)
            rejections = [p for p in problems if p.startswith("REJECTED")]
            if rejections:
                print(f"\n🚫 Attempt {attempt}: LLM tried to rewrite user scripts:")
                for p in rejections:
                    print(f"   {p}")
                if attempt < max_attempts:
                    print("   Retrying...\n")
                    user_names = ", ".join(s["name"] for s in scan["scripts"])
                    glue_prompt += (
                        f"\n\n=== REJECTED: do NOT generate files named: {user_names} ===\n"
                        "Generate ONLY new files under glue/.\n"
                    )
                    continue
                # Last attempt: filter out conflicting files
                user_name_set = {s["name"] for s in scan["scripts"]}
                glue_files = {
                    k: v for k, v in glue_files.items()
                    if k.replace("glue/", "").strip("/") not in user_name_set
                }
            print(f"\n📄 Generated {len(glue_files)} file(s):")
            for fname, content in glue_files.items():
                lines = content.count("\n")
                print(f"   {fname} ({lines} lines)")
            break

        else:
            # glue_only: strict validation (original behavior)
            problems = _validate_glue_output(glue_files, scan)
            rejections = [p for p in problems if p.startswith("REJECTED")]

            if rejections:
                print(f"\n🚫 Attempt {attempt}/{max_attempts}: LLM tried to rewrite user scripts:")
                for p in rejections:
                    print(f"   {p}")

                if attempt < max_attempts:
                    print("   Retrying with stronger constraint...\n")
                    rejection_feedback = (
                        "\n\n=== PREVIOUS ATTEMPT REJECTED ===\n"
                        "Your previous output was REJECTED because you generated files "
                        "that rewrite the user's existing scripts.  You generated:\n"
                        + "\n".join(f"  ❌ {fname}" for fname in glue_files.keys())
                        + "\n\nThe user already has these scripts (DO NOT REGENERATE):\n"
                        + "\n".join(f"  {s['name']}" for s in scan["scripts"])
                        + "\n\nGenerate ONLY glue/prepare_and_launch.sh — ONE file that "
                        "transforms xyz/*.xyz into the format the entry-point expects.\n"
                        "=== END FEEDBACK ===\n"
                    )
                    glue_prompt = glue_prompt + rejection_feedback
                    continue
                else:
                    print(f"   ❌ Failed after {max_attempts} attempts.")
                    if not non_interactive and confirm("Write anyway (you can fix manually)?"):
                        user_names = {s["name"] for s in scan["scripts"]}
                        glue_files = {
                            k: v for k, v in glue_files.items()
                            if k.replace("glue/", "").strip("/") not in user_names
                        }
                        break
                    return False
            else:
                # Passed validation
                warnings = [p for p in problems if p.startswith("WARNING")]
                if warnings:
                    for w in warnings:
                        print(f"   ⚠  {w}")
                break

    # Show what will be generated
    print(f"\n  Generated {len(glue_files)} glue script(s):")
    for fname in sorted(glue_files.keys()):
        lines = glue_files[fname].count("\n")
        print(f"    {fname} ({lines} lines)")

    if not non_interactive:
        for fname, content in sorted(glue_files.items()):
            print(f"\n📄 {fname}:\n")
            show_lines = content.split("\n")[:80]
            for line in show_lines:
                print(f"  {line}")
            if content.count("\n") > 80:
                print(f"  ... ({content.count(chr(10)) - 80} more lines)")
            print()

        if not confirm("Accept these glue scripts?"):
            return False

    # ── Phase 4: Write everything ─────────────────────────────────────
    print("\n📝 Writing files...\n")

    manifest_path = plugin_dir / "plugin.yaml"
    if manifest_path.exists():
        backup = plugin_dir / "plugin.yaml.bak"
        shutil.copy2(manifest_path, backup)
        print(f"  📦 Backed up plugin.yaml → plugin.yaml.bak")

    manifest_path.write_text(yaml_text)
    print(f"  ✅ Wrote plugin.yaml")

    glue_dir = plugin_dir / "glue"
    if glue_dir.exists():
        backup_glue = plugin_dir / "glue.bak"
        if backup_glue.exists():
            shutil.rmtree(backup_glue)
        shutil.move(str(glue_dir), str(backup_glue))
        print(f"  📦 Backed up glue/ → glue.bak/")

    glue_dir.mkdir(parents=True, exist_ok=True)

    for fname, content in glue_files.items():
        clean_name = fname.replace("glue/", "")
        fpath = glue_dir / clean_name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        fpath.chmod(fpath.stat().st_mode | stat.S_IEXEC)
        print(f"  ✅ Wrote glue/{clean_name}")

    # ── Phase 5: Validate ─────────────────────────────────────────────
    print("\n🔍 Running validation...\n")
    errors = validate_plugin(plugin_dir)
    if errors:
        print("⚠  Validation notes:")
        for e in errors:
            print(f"   • {e}")
    else:
        print("✅ Plugin is valid!")

    print(f"\n  Next steps:")
    print(f"    1. Review the generated files")
    print(f"    2. ./golddigr plugin register {plugin_dir}")
    print(f"    3. ./golddigr plugin package {parsed_manifest.get('name', 'your-plugin')}")
    print()

    return True
