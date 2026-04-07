"""
pipeline.plugins.porter – Port a workflow to a different scheduler.

Given an existing plugin (with working glue scripts for scheduler A),
generates new glue scripts for scheduler B.  The science scripts are
never touched — only the operations layer is regenerated.

Supports: SLURM ↔ HTCondor ↔ SGE ↔ PBS/Torque ↔ local
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .registry import load_manifest
from ._utils import call_llm, confirm, parse_multi_file_output

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# System prompt
# ═══════════════════════════════════════════════════════════════════════

_PORT_SYSTEM = """\
You are an HPC systems engineer porting a computational chemistry workflow \
from one job scheduler to another.

You will receive:
- The plugin manifest (plugin.yaml) — describes the workflow
- The CURRENT glue scripts (written for scheduler A)
- The CURRENT operations scripts (the user's submission/monitoring code)
- The TARGET scheduler name and optionally a submit template

Your job: generate NEW glue scripts for the TARGET scheduler.

CRITICAL RULES:

1. NEVER modify the science/driver script. The per-job computation script \
(e.g., run_orca_wbo.sh) is scheduler-independent and must be called as-is.

2. The data-adapter part of the glue (xyz→zip transformation) should be \
PRESERVED exactly. Only the scheduler-specific parts change.

3. Map OPERATIONAL INTENT, not just commands. For example:
   HTCondor "held job → release with more memory" becomes
   SLURM "failed job → resubmit with --mem=X"

4. Preserve these operational features if the source workflow has them:
   - Queue throttling (max concurrent jobs)
   - Resource escalation (auto-increase memory/CPU on failure)
   - Health monitoring (detect and fix stuck/held jobs)
   - Result backup
   - Round-2 resubmission (for timeouts)

5. CRITICAL: The user's entry-point script (e.g., start.sh) is almost \
certainly SCHEDULER-SPECIFIC.  It likely calls condor_submit, sbatch, or \
qsub directly.  DO NOT call the original start.sh from the ported glue.  \
Instead, the ported prepare_and_launch.sh must:
   a) Do the data transformation (same as before)
   b) Do the setup that start.sh does (extract archives, build file lists, \
      create directories, split into chunks) — replicated directly in the glue
   c) Call the NEW scheduler-specific submission scripts (e.g., \
      glue/monitor_submit_sge.sh) instead of the old start.sh

Think of it this way: the ported glue REPLACES both the old glue AND the \
old start.sh.  The only user scripts that should still be called are the \
science/driver scripts (e.g., run_orca_wbo.sh).

SCHEDULER TRANSLATION TABLE:

| Concept            | HTCondor              | SLURM                  | SGE                    | PBS/Torque            |
|--------------------|----------------------|------------------------|------------------------|-----------------------|
| Submit             | condor_submit        | sbatch                 | qsub                   | qsub                 |
| Queue status       | condor_q             | squeue                 | qstat                  | qstat                 |
| Cancel             | condor_rm            | scancel                | qdel                   | qdel                  |
| Hold/release       | condor_hold/release  | scontrol hold/release  | qhold/qrls             | qhold/qrls            |
| Job status         | JobStatus ClassAd    | -o %T                  | qstat -j               | qstat -f              |
| Memory request     | request_memory       | --mem                  | -l h_vmem              | -l mem                |
| CPU request        | request_cpus         | --cpus-per-task        | -pe smp N              | -l ncpus              |
| Wall time          | +MaxRunTime          | --time                 | -l h_rt                | -l walltime           |
| File transfer      | transfer_input_files | shared filesystem      | shared filesystem       | shared filesystem     |
| Container          | +SingularityImage    | --container            | singularity exec        | singularity exec      |
| Array jobs         | queue N              | --array=1-N            | -t 1-N                 | -J 1-N                |

IMPORTANT DIFFERENCES:
- HTCondor transfers files in/out. SLURM/SGE/PBS assume shared filesystem.
  When porting FROM HTCondor: add explicit file copy/link commands.
  When porting TO HTCondor: add transfer_input_files directives.
- HTCondor ClassAds are powerful expressions. SLURM uses simpler flags.
- SGE uses -pe for parallel environments; SLURM uses --ntasks/--cpus-per-task.

CRITICAL SGE PITFALL — JOB SCRIPT PATH RESOLUTION:
SGE copies job scripts to a spool directory on the compute node \
(e.g., /opt/sge/.../job_scripts/12345). This means any script submitted \
via qsub CANNOT use $(dirname "$0") or $0 to find sibling files — it will \
resolve to the spool directory, not the original submission directory.

SOLUTION: In ALL scripts submitted via qsub, use $SGE_O_WORKDIR (which SGE \
always sets to the directory where qsub was called) instead of computing \
paths from $0. Example:
  WRONG:  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  RIGHT:  WORKDIR="${SGE_O_WORKDIR}"

This applies to both the array runner and the task wrapper. SLURM does not \
have this issue (it runs scripts in-place via srun/sbatch with --chdir).

OUTPUT FORMAT:
Generate scripts using the === FILE: glue/filename.sh === format.

You should generate:
1. glue/prepare_and_launch.sh — data transformation + setup + launch \
(replaces BOTH the old glue AND the old entry-point script like start.sh)
2. A per-job task wrapper that calls the science/driver script
3. Additional glue scripts for monitoring, health checks, etc. as needed

NEVER include a line that calls the user's original start.sh or any other \
scheduler-specific user script.  The ported glue IS the new start.sh.

No markdown fences. No explanation outside the files.
"""


def _build_port_prompt(
    manifest: Dict,
    current_glue: Dict[str, str],
    operations_scripts: Dict[str, str],
    target_scheduler: str,
    target_template: str = "",
    readme: str = "",
) -> str:
    """Build the user prompt for porting."""
    parts = []

    # Manifest
    parts.append(f"=== plugin.yaml ===\n{yaml.dump(manifest, default_flow_style=False)}\n=== END ===\n")

    # Current scheduler
    current = manifest.get("scheduler", "unknown")
    parts.append(f"=== PORTING: {current.upper()} → {target_scheduler.upper()} ===\n")

    # Current glue scripts
    parts.append("=== CURRENT GLUE SCRIPTS (for source scheduler) ===")
    for name, content in sorted(current_glue.items()):
        parts.append(f"--- {name} ---\n{content[:5000]}")
    parts.append("=== END CURRENT GLUE ===\n")

    # User's operations scripts (to understand intent)
    if operations_scripts:
        parts.append("=== USER'S OPERATIONS SCRIPTS (read for INTENT, not to copy) ===")
        parts.append("These scripts implement monitoring, health-checking, backup, etc.")
        parts.append("Map their INTENT to the target scheduler, don't transliterate.\n")
        for name, content in sorted(operations_scripts.items()):
            # Send summaries + first 80 lines
            lines = content.split("\n")
            parts.append(f"--- {name} ({len(lines)} lines) ---")
            parts.append("\n".join(lines[:80]))
            if len(lines) > 80:
                parts.append(f"... ({len(lines) - 80} more lines)")
        parts.append("=== END OPERATIONS SCRIPTS ===\n")

    # README for operational context
    if readme:
        parts.append(f"=== README / WORKFLOW DESCRIPTION ===\n{readme[:5000]}\n=== END ===\n")

    # Target template
    if target_template:
        parts.append(f"=== TARGET SCHEDULER TEMPLATE ===\n{target_template[:3000]}\n=== END ===\n")

    # Final instruction
    parts.append(
        f"Generate new glue scripts for {target_scheduler.upper()}.\n"
        f"Preserve the data-adapter logic (xyz → zip/tar transformation) exactly.\n"
        f"Replace all {current}-specific commands with {target_scheduler} equivalents.\n"
        f"Map operational features (throttling, health monitoring, escalation) to {target_scheduler}.\n"
    )

    return "\n".join(parts)




# ═══════════════════════════════════════════════════════════════════════
# Main port function
# ═══════════════════════════════════════════════════════════════════════

def port_plugin(
    plugin_dir: Path,
    target_scheduler: str,
    *,
    target_template: Optional[Path] = None,
    provider: str = "openai",
    model: str = "gpt-4o",
    non_interactive: bool = False,
) -> bool:
    """
    Port a plugin's glue scripts to a different scheduler.

    1. Reads current glue + operations scripts
    2. Sends to LLM with target scheduler info
    3. Generates new glue scripts
    4. User confirms
    5. Backs up old glue/ → glue.{old_scheduler}.bak/
    6. Writes new glue scripts
    7. Updates plugin.yaml scheduler field

    Returns True if new scripts were written.
    """
    plugin_dir = Path(plugin_dir).resolve()
    manifest = load_manifest(plugin_dir)
    plugin_name = manifest.get("name", "unknown")
    current_scheduler = manifest.get("scheduler", "unknown")

    valid_schedulers = ("slurm", "htcondor", "sge", "pbs", "local")
    if target_scheduler not in valid_schedulers:
        print(f"❌ Unknown scheduler: '{target_scheduler}'")
        print(f"   Supported: {', '.join(valid_schedulers)}")
        return False

    if target_scheduler == current_scheduler:
        print(f"⚠  Plugin already uses {target_scheduler}. Nothing to port.")
        return False

    print(f"\n🔄 Porting: {plugin_name}")
    print(f"   {current_scheduler.upper()} → {target_scheduler.upper()}\n")

    # ── Load current glue scripts ─────────────────────────────────────
    current_glue = {}
    glue_dir = plugin_dir / "glue"
    if glue_dir.is_dir():
        for f in sorted(glue_dir.iterdir()):
            if f.is_file():
                current_glue[f.name] = f.read_text(errors="ignore")
        print(f"   Current glue: {len(current_glue)} scripts")
    else:
        print("❌ No glue/ directory. Run 'plugin init' first.")
        return False

    # ── Load operations scripts (for intent extraction) ───────────────
    operations = {}
    scripts_dir = plugin_dir / "scripts"
    script_dirs = [scripts_dir] if scripts_dir.is_dir() else []

    # Also check flat layout
    for f in plugin_dir.iterdir():
        if f.is_file() and f.suffix in (".sh", ".submit") and f.name not in ("plugin.yaml",):
            operations[f.name] = f.read_text(errors="ignore")

    if scripts_dir.is_dir():
        for f in scripts_dir.rglob("*"):
            if f.is_file() and f.suffix in (".sh", ".submit"):
                operations[f.name] = f.read_text(errors="ignore")

    print(f"   Operations scripts: {len(operations)}")

    # ── Load README for context ───────────────────────────────────────
    readme = ""
    for name in ("README.md", "WORKFLOW.md"):
        rp = plugin_dir / name
        if rp.exists():
            readme += rp.read_text(errors="ignore")[:5000] + "\n"

    # ── Load target template if provided ──────────────────────────────
    template_content = ""
    if target_template and Path(target_template).exists():
        template_content = Path(target_template).read_text(errors="ignore")
        print(f"   Target template: {target_template}")

    # ── Build prompt and call LLM ─────────────────────────────────────
    print(f"\n🤖 Generating {target_scheduler} glue via {provider}/{model}...\n")

    # Probe target infrastructure
    infra_context = ""
    try:
        from .probe import probe_infrastructure, format_probe_report, format_probe_for_prompt
        infra = probe_infrastructure()
        print(format_probe_report(infra))
        print()
        infra_context = format_probe_for_prompt(infra)
    except Exception as e:
        logger.debug("Infrastructure probe failed: %s", e)

    # Load catalog for known pitfalls
    catalog_context = ""
    try:
        from .catalog import load_catalog
        catalog = load_catalog(plugin_dir.parent)
        cat_plugins = catalog.get("plugins", {})
        if cat_plugins:
            relevant_issues = []
            for pname, pentry in cat_plugins.items():
                for issue in pentry.get("known_issues", []):
                    if isinstance(issue, dict):
                        sched = issue.get("scheduler", "")
                        if sched == target_scheduler or sched == current_scheduler:
                            relevant_issues.append(issue)

                # Also grab infrastructure info from catalog
                cat_infra = pentry.get("infrastructure", {})
                if cat_infra:
                    catalog_context += f"\n=== INFRASTRUCTURE: {pname} ===\n"
                    catalog_context += yaml.dump(cat_infra, default_flow_style=False)
                    catalog_context += "=== END ===\n"

            if relevant_issues:
                catalog_context += "\n=== KNOWN ISSUES FROM CATALOG ===\n"
                catalog_context += "Apply these lessons proactively:\n"
                for issue in relevant_issues:
                    catalog_context += (
                        f"  - [{issue.get('scheduler', '?')}] {issue.get('issue', '?')}\n"
                        f"    Fix: {issue.get('fix', '?')}\n"
                    )
                catalog_context += "=== END KNOWN ISSUES ===\n"
                print(f"   📖 Loaded {len(relevant_issues)} known issue(s) from catalog")
    except Exception:
        pass

    prompt = _build_port_prompt(
        manifest, current_glue, operations,
        target_scheduler, template_content, readme,
    )
    if infra_context:
        prompt += "\n" + infra_context
    if catalog_context:
        prompt += "\n" + catalog_context

    try:
        raw = call_llm(provider, model, _PORT_SYSTEM, prompt)
    except Exception as e:
        logger.error("LLM API error during porting: %s", e)
        print(f"❌ LLM API error: {e}")
        return False

    new_glue = parse_multi_file_output(raw)

    if not new_glue:
        print("❌ LLM returned empty output.")
        return False

    # ── Validate: catch calls to scheduler-specific user scripts ──────
    # Identify which user scripts are scheduler-specific (contain scheduler commands)
    source_scheduler_cmds = {
        "htcondor": ["condor_submit", "condor_q", "condor_rm", "condor_hold", "condor_release"],
        "slurm": ["sbatch", "squeue", "scancel", "scontrol"],
        "sge": ["qsub", "qstat", "qdel", "qhold", "qrls"],
        "pbs": ["qsub", "qstat", "qdel", "qhold", "qrls"],
    }
    src_cmds = source_scheduler_cmds.get(current_scheduler, [])

    scheduler_specific_scripts = set()
    for sname, scontent in operations.items():
        if any(cmd in scontent for cmd in src_cmds):
            scheduler_specific_scripts.add(sname)

    # Check if generated glue calls any scheduler-specific user script
    warnings = []
    for fname, content in new_glue.items():
        for sname in scheduler_specific_scripts:
            # Look for direct calls: ./start.sh, "$WORKDIR/start.sh", exec start.sh, etc.
            if re.search(rf'(?:exec|bash|source|\./|"\$\w+/)?\s*{re.escape(sname)}', content):
                warnings.append(
                    f"⚠  {fname} calls '{sname}' which is {current_scheduler}-specific "
                    f"(contains {current_scheduler} commands). This will fail on {target_scheduler}."
                )

    if warnings:
        print(f"\n🚫 Ported glue still references {current_scheduler}-specific scripts:")
        for w in warnings:
            print(f"   {w}")
        print(f"\n   The ported glue should NOT call these scripts.")
        print(f"   Retrying with stronger constraint...\n")

        retry_feedback = (
            f"\n\n=== PREVIOUS ATTEMPT REJECTED ===\n"
            f"Your generated glue still calls the user's {current_scheduler}-specific "
            f"entry-point scripts:\n"
            + "\n".join(f"  ❌ {sname} (contains {current_scheduler} commands)"
                        for sname in scheduler_specific_scripts)
            + f"\n\nThe ported glue must REPLACE these scripts entirely. "
            f"Do NOT call start.sh or any other {current_scheduler}-specific script.\n"
            f"The ported prepare_and_launch.sh should:\n"
            f"  1. Transform xyz → zips → tar.gz (data adapter — same as before)\n"
            f"  2. Extract the tar.gz, build file lists, create directories "
            f"(replicate what start.sh does)\n"
            f"  3. Submit jobs using {target_scheduler} commands ({', '.join(source_scheduler_cmds.get(target_scheduler, ['qsub']))})\n"
            f"  4. Start monitoring using the generated {target_scheduler} monitor scripts\n"
            f"=== END FEEDBACK ===\n"
        )
        prompt = prompt + retry_feedback

        try:
            raw = call_llm(provider, model, _PORT_SYSTEM, prompt)
        except Exception as e:
            logger.error("LLM API retry error during porting: %s", e)
            print(f"❌ LLM API retry error: {e}")
            return False

        new_glue = parse_multi_file_output(raw)
        if not new_glue:
            print("❌ Retry returned empty output.")
            return False

    # ── Show results ──────────────────────────────────────────────────
    print(f"   Generated {len(new_glue)} scripts for {target_scheduler}:")
    for fname in sorted(new_glue.keys()):
        lines = new_glue[fname].count("\n")
        print(f"     {fname} ({lines} lines)")

    if not non_interactive:
        for fname, content in sorted(new_glue.items()):
            print(f"\n📄 {fname}:\n")
            show_lines = content.split("\n")[:80]
            for line in show_lines:
                print(f"  {line}")
            if content.count("\n") > 80:
                print(f"  ... ({content.count(chr(10)) - 80} more lines)")
            print()

        if not confirm("Accept these ported glue scripts?"):
            return False

    # ── Backup and write ──────────────────────────────────────────────
    print("\n📝 Writing files...\n")

    # Backup current glue
    backup_name = f"glue.{current_scheduler}.bak"
    backup_dir = plugin_dir / backup_name
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(glue_dir, backup_dir)
    print(f"  📦 Backed up glue/ → {backup_name}/")

    # Clear glue directory
    for f in glue_dir.iterdir():
        if f.is_file():
            f.unlink()

    # Write new glue scripts
    for fname, content in new_glue.items():
        clean_name = fname.replace("glue/", "")
        fpath = glue_dir / clean_name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        fpath.chmod(fpath.stat().st_mode | stat.S_IEXEC)
        print(f"  ✅ Wrote glue/{clean_name}")

    # Update plugin.yaml scheduler field
    manifest["scheduler"] = target_scheduler
    manifest_path = plugin_dir / "plugin.yaml"
    shutil.copy2(manifest_path, plugin_dir / "plugin.yaml.pre-port.bak")
    manifest_path.write_text(yaml.dump(manifest, default_flow_style=False))
    print(f"  ✅ Updated plugin.yaml: scheduler → {target_scheduler}")

    print(f"\n  Porting complete! Next steps:")
    print(f"    1. Review the generated glue scripts")
    print(f"    2. ./golddigr plugin pilot {plugin_name}")
    print(f"       (test on the new cluster before full launch)")
    print()

    return True
