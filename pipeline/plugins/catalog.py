"""
pipeline.plugins.catalog – Plugin knowledge base builder.

Three-phase validation + cataloging:
  Phase 1: Static scan — grep scripts for references to missing files
  Phase 2: LLM audit — read all scripts + README, check workflow completeness
  Phase 3: Cross-reference — compare with already-cataloged plugins

Only records complete, validated plugins into _catalog.yaml.
The catalog is read by plugin init to inform glue generation for new plugins.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger(__name__)

_CATALOG_FILENAME = "_catalog.yaml"
_MAX_SCRIPT_CHARS = 15_000

# Import from library module
try:
    from .library import LIBRARY_DIR
except ImportError:
    LIBRARY_DIR = "_library"

from ._utils import call_llm, ask_user, confirm, fix_yaml_quoting


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: Static reference scan
# ═══════════════════════════════════════════════════════════════════════

def _scan_references(plugin_dir: Path) -> List[Dict[str, str]]:
    """
    Grep all scripts for references to other files (source, bash, python3,
    cp, cat, etc.) and check whether those files exist.

    Returns list of: {"source_file", "line_num", "reference", "type", "exists"}
    """
    refs = []
    plugin_dir = Path(plugin_dir)

    from .ignore import load_ignore_patterns, should_ignore
    ig_patterns = load_ignore_patterns(plugin_dir)

    # All files in the plugin (filtered)
    all_files = set()
    for f in plugin_dir.rglob("*"):
        if f.is_file():
            if should_ignore(f, plugin_dir, ig_patterns):
                continue
            all_files.add(f.name)
            all_files.add(str(f.relative_to(plugin_dir)))

    # Patterns that reference other files
    patterns = [
        # source/dot
        (r'(?:source|\.) +["\']?([./\w_-]+\.(?:sh|env|conf))["\']?', "source"),
        # bash/sh execution
        (r'(?:bash|sh) +["\']?([./\w_-]+\.sh)["\']?', "execute"),
        # python3 execution
        (r'python3? +["\']?([./\w_-]+\.py)["\']?', "python"),
        # explicit script call with path
        (r'\$[{(]?(?:SCRIPT_DIR|WORKDIR|PKG_DIR)[})]?/([./\w_-]+\.(?:sh|py|submit|env|conf))', "path_ref"),
        # cp/cat/mv of templates or configs
        (r'(?:cp|cat|mv) +.*?["\']?([./\w_-]+\.(?:template|inp|yaml|yml|conf|env))["\']?', "file_op"),
        # direct ./script.sh execution
        (r'\./([.\w_-]+\.sh)', "direct_exec"),
    ]

    for f in plugin_dir.rglob("*"):
        if not f.is_file() or f.suffix not in (".sh", ".py", ".bash", ".submit"):
            continue
        if should_ignore(f, plugin_dir, ig_patterns):
            continue

        try:
            lines = f.read_text(errors="ignore").splitlines()
        except Exception:
            continue

        rel_source = str(f.relative_to(plugin_dir))

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments
            if stripped.startswith("#"):
                continue

            for pattern, ref_type in patterns:
                for match in re.finditer(pattern, line):
                    ref_name = match.group(1)
                    # Normalize: strip leading ./
                    ref_clean = ref_name.lstrip("./")

                    # Check existence (by name or relative path)
                    exists = (
                        ref_clean in all_files or
                        (plugin_dir / ref_clean).exists() or
                        ref_name in all_files
                    )

                    # Skip self-references and common system commands
                    if ref_clean == rel_source:
                        continue
                    if ref_clean in ("run.yaml", "/dev/null", "/tmp"):
                        continue

                    refs.append({
                        "source_file": rel_source,
                        "line_num": line_num,
                        "reference": ref_clean,
                        "type": ref_type,
                        "exists": exists,
                    })

    return refs


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: LLM workflow audit
# ═══════════════════════════════════════════════════════════════════════

_AUDIT_SYSTEM = """\
You are auditing a computational workflow plugin for completeness.

You will receive:
- All scripts in the plugin (full content)
- README/WORKFLOW documentation (if present)
- A list of files that are referenced but missing (from static analysis)

Your job: identify GAPS in the workflow. A gap is:
1. A script referenced by another script but not present in the plugin
2. A step described in the README but not implemented by any script
3. A configuration file or template expected by a script but not provided
4. A logical step that's obviously needed but not present (e.g., a workflow \
   that runs ORCA but has no ORCA input template, or a workflow that submits \
   jobs but has no monitoring/health script)

For each gap, output:

=== GAP: short_name ===
Type: missing_file | missing_step | missing_config | missing_template
Referenced_by: which_script.sh (line N) or README.md
Description: Clear explanation of what's missing and why it matters
Severity: critical (workflow will fail) | warning (will work but incomplete)
Question: A clear question to ask the user about this gap

If no gaps are found, output:
=== NO_GAPS ===

RULES:
- Do NOT flag optional features (nice-to-have monitoring, status scripts)
- DO flag anything that would cause the core workflow to fail
- DO flag missing input templates or configuration files
- Consider the workflow end-to-end: input preparation → job execution → result collection
- If the README mentions a step but a script handles it internally (e.g., ORCA \
  input generation is hardcoded in the driver script), that's NOT a gap
"""

_CATALOG_SYSTEM = """\
You are a knowledge engineer documenting a validated computational workflow \
plugin. Your output will be used by future LLM calls to understand patterns \
and generate analogous workflows.

You will receive:
- All scripts in the plugin (full content)
- README/documentation
- plugin.yaml manifest
- Glue scripts (if present)
- Diagnosis/fix history (if present — contains known pitfalls)

Generate a YAML catalog entry that captures:
1. WHAT the plugin does (high-level)
2. HOW each file contributes (role + concepts)
3. PATTERNS that are reusable in other workflows
4. PITFALLS discovered during testing
5. INFRASTRUCTURE requirements and assumptions

OUTPUT FORMAT (raw YAML only, no fences):

input_type: "xyz"
input_format: "description of what golddigr provides"
output_type: "description of what the workflow produces"

computation:
  tool: "name of main computation tool"
  type: "container | script | binary"
  container: "container image description (if applicable)"
  key_features:
    - "feature 1"
    - "feature 2"

scheduler_tested:
  - "sge"
  - "htcondor"

infrastructure:
  filesystem: "shared | isolated | htcondor_transfer"
  filesystem_details: "e.g., AFS/NFS shared across nodes, or HTCondor file transfer"
  container_delivery: "local_path | osdf | cvmfs | docker_pull"
  container_path: "path or URI to the container image"
  mpi: "host_openmpi | host_intelmpi | inside_container | none"
  mpi_scheduler_integration: "description of any MPI-scheduler issues"
  gpu_required: true/false
  internet_required: true/false
  special_requirements:
    - "any cluster-specific requirements (modules, paths, env vars)"

files:
  filename.sh:
    role: "driver | entry_point | operational | adapter | config"
    description: "what this file does"
    concepts:
      - name: "concept_name"
        description: "what this concept is"
        transferable: true/false
        lines: "approximate line range"

patterns:
  input_adaptation: "how golddigr output is transformed for this workflow"
  job_submission: "how jobs are submitted (array, individual, etc.)"
  resource_management: "memory escalation, CPU scaling, etc."
  monitoring: "health checks, auto-healing, backup"
  result_collection: "how results are gathered and formatted"
  charge_mult: "how charge and multiplicity are determined (if applicable)"

known_issues:
  - scheduler: "sge"
    issue: "description of the problem"
    fix: "how it was resolved"
    pattern: "general pattern to watch for"

glue_strategy: "one-line description of the glue approach"

reusable_for:
  - "description of what similar workflows could reuse from this plugin"

IMPORTANT for the infrastructure section:
- Infer filesystem model from the scripts: if they use transfer_input_files, \
  it's HTCondor file transfer (isolated). If they use absolute paths to shared \
  dirs (/scratch, /users, /afs), it's shared filesystem.
- Infer container delivery from how the SIF is referenced: osdf:// URIs mean \
  OSDF delivery; local absolute paths mean pre-staged; +SingularityImage with \
  osdf:// means HTCondor fetches it.
- Infer MPI model from how mpirun is invoked: if inside a container wrapper, \
  it's container MPI; if on bare host, it's host MPI. Note any PE_HOSTFILE or \
  OMPI_MCA settings.

Output ONLY raw YAML. No markdown fences, no explanation text outside YAML.
"""


_WORKFLOW_GRAPH_SYSTEM = """\
You are a workflow architecture analyzer. You will receive all scripts, \
templates, README, and plugin.yaml from a computational chemistry plugin.

Your job: extract the DIRECTED ACYCLIC GRAPH of execution stages.

For each stage/node, identify:
- id: matches the stage name in plugin.yaml (if present), or a short slug
- type: one of compute, analysis, stats, visualization, adapter
  - compute = runs a computational tool (xTB, ORCA, Gaussian, pysisyphus)
  - analysis = processes compute outputs (parsing, BEM, WBO extraction)
  - stats = post-hoc aggregation/summarization
  - visualization = generates plots/diagrams/sankey
  - adapter = data format transformation (xyz→zip, charge/mult derivation)
- tool: the computational tool used (xtb, pysisyphus, orca, yarp, python, bash)
- scripts: list of script paths that implement this stage
- templates: list of objects with path and placeholders for templates used
- inputs: files/directories this stage reads (use the ACTUAL filenames from scripts)
- outputs: files/directories this stage produces
- description: one-line summary

For each edge, identify:
- from: source node id
- to: target node id
- gate: condition that must be met before target runs:
  - type: file_exists | directory_exists | imaginary_freq | exit_code | custom
  - file: the file to check (if applicable)
  - threshold: numeric threshold (if applicable)
  - description: human-readable gate description

Also identify:
- entry_point: the script that orchestrates the pipeline (NOT the stats script)
- per_job_runner: the script submitted per-job to the scheduler
- execution_order: flat list of node ids in execution order
- template_placeholders: dict mapping placeholder names to descriptions

RULES:
- If plugin.yaml has stages with gates, use those stage names and gates
- Trace data flow by reading scripts: what does stage N write that stage N+1 reads?
- The entry_point is the ORCHESTRATION script, not a post-hoc stats/analysis script
- Template files (.template) define compute parameters — capture their placeholders
- For multi-stage pipelines, distinguish compute stages from analysis/stats stages
- Single-stage plugins get one node with id "main"

OUTPUT FORMAT (raw YAML only, no fences, no explanation):

entry_point: "path/to/entry.sh"
per_job_runner: "path/to/runner.sh"

nodes:
  - id: "stage_name"
    type: "compute"
    tool: "tool_name"
    scripts:
      - "path/to/script.sh"
    templates:
      - path: "path/to/template"
        placeholders:
          - "PLACEHOLDER_NAME"
    inputs:
      - "input_file_or_pattern"
    outputs:
      - "output_file_or_dir"
    description: "what this stage does"

edges:
  - from: "source_id"
    to: "target_id"
    gate:
      type: "gate_type"
      file: "gate_file"
      description: "human-readable description"

execution_order:
  - "stage_1"
  - "stage_2"

template_placeholders:
  PLACEHOLDER_NAME: "description of what to fill in"

Output ONLY raw YAML. No markdown fences, no explanation text.
"""


def _validate_workflow_graph(graph):
    """Validate a workflow graph structure. Returns (valid, issues)."""
    issues = []

    if not isinstance(graph, dict):
        return False, ["Graph must be a dict"]

    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or len(nodes) == 0:
        return False, ["'nodes' must be a non-empty list"]

    node_ids = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            issues.append("Node %d is not a dict" % i)
            continue
        nid = node.get("id")
        if not nid:
            issues.append("Node %d missing 'id'" % i)
        else:
            if nid in node_ids:
                issues.append("Duplicate node id: %s" % nid)
            node_ids.add(nid)

        ntype = node.get("type", "")
        valid_types = ("compute", "analysis", "stats", "visualization", "adapter", "")
        if ntype not in valid_types:
            issues.append("Node '%s': unknown type '%s'" % (nid, ntype))

    edges = graph.get("edges", [])
    if not isinstance(edges, list):
        issues.append("'edges' must be a list")
        edges = []

    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            issues.append("Edge %d is not a dict" % i)
            continue
        efrom = edge.get("from", "")
        eto = edge.get("to", "")
        if efrom and efrom not in node_ids:
            issues.append("Edge %d: 'from' references unknown node '%s'" % (i, efrom))
        if eto and eto not in node_ids:
            issues.append("Edge %d: 'to' references unknown node '%s'" % (i, eto))

    exec_order = graph.get("execution_order", [])
    if isinstance(exec_order, list):
        for eid in exec_order:
            if eid not in node_ids:
                issues.append("execution_order references unknown node '%s'" % eid)

    # Only fail on structural issues, not missing optional fields
    critical = [i for i in issues if "non-critical" not in i
                and "missing" not in i.lower()]
    return len(critical) == 0, issues


def extract_workflow_graph(plugin_dir, scan, provider="openai", model="gpt-4o"):
    """Extract a workflow DAG from a plugin's scripts, templates, and manifest.

    Uses a single LLM call to analyze all plugin content and produce a
    structured workflow graph capturing stage dependencies, gate conditions,
    template placeholders, and execution order.

    Returns the graph dict, or None on failure.
    """
    from pathlib import Path
    import yaml as _yaml
    from ._utils import call_llm, fix_yaml_quoting

    plugin_dir = Path(plugin_dir)
    content_text, _ = _build_plugin_content(plugin_dir)

    prompt = (
        content_text + "\n\n"
        "Extract the workflow graph from this plugin.\n"
        "Trace data flow through scripts and templates to identify all stages,\n"
        "their dependencies, and gate conditions.\n"
        "Output ONLY raw YAML.\n"
    )

    print("   Asking %s/%s for workflow graph..." % (provider, model))
    try:
        raw = call_llm(provider, model, _WORKFLOW_GRAPH_SYSTEM, prompt, 0.2,
                        max_tokens=8192)
    except Exception as e:
        logger.error("LLM error during workflow graph extraction: %s", e)
        print("   ❌ LLM error: %s" % e)
        return None

    # Clean up response
    raw = raw.strip()
    if raw.startswith("```"):
        import re
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    raw = fix_yaml_quoting(raw)

    try:
        graph = _yaml.safe_load(raw)
    except _yaml.YAMLError as e:
        logger.error("Failed to parse workflow graph YAML: %s", e)
        print("   ❌ YAML parse error: %s" % e)
        return None

    if not isinstance(graph, dict):
        print("   ❌ Graph is not a dict")
        return None

    valid, issues = _validate_workflow_graph(graph)
    if issues:
        for issue in issues:
            logger.debug("Workflow graph issue: %s", issue)
    if not valid:
        print("   ❌ Graph validation failed:")
        for issue in issues:
            print("      %s" % issue)
        return None

    return graph


def format_workflow_graph_for_prompt(graph):
    """Format a workflow graph as a concise text block for LLM prompts.

    Returns empty string if graph is None or empty.
    """
    if not graph or not isinstance(graph, dict):
        return ""

    nodes = graph.get("nodes", [])
    if not nodes:
        return ""

    parts = ["=== WORKFLOW GRAPH ==="]

    entry = graph.get("entry_point", "?")
    runner = graph.get("per_job_runner", "?")
    parts.append("Entry point: %s" % entry)
    parts.append("Per-job runner: %s" % runner)
    parts.append("")

    # Build edge lookup for gates
    edge_map = {}
    for edge in graph.get("edges", []):
        edge_map[edge.get("from", "")] = edge

    exec_order = graph.get("execution_order", [n["id"] for n in nodes])
    parts.append("Execution pipeline (%d stages):" % len(exec_order))

    node_map = {n["id"]: n for n in nodes}
    for i, nid in enumerate(exec_order, 1):
        node = node_map.get(nid, {})
        ntype = node.get("type", "?")
        tool = node.get("tool", "?")
        desc = node.get("description", "")

        inputs = ", ".join(node.get("inputs", []))
        outputs = ", ".join(node.get("outputs", []))

        parts.append("  %d. %s [%s/%s]" % (i, nid, ntype, tool))
        if desc:
            parts.append("     %s" % desc)
        parts.append("     In: %s → Out: %s" % (inputs or "?", outputs or "?"))

        # Scripts
        scripts = node.get("scripts", [])
        if scripts:
            parts.append("     Scripts: %s" % ", ".join(scripts))

        # Templates
        templates = node.get("templates", [])
        for t in templates:
            pholders = ", ".join(t.get("placeholders", []))
            parts.append("     Template: %s (%s)" % (t.get("path", "?"), pholders))

        # Gate to next
        edge = edge_map.get(nid)
        if edge:
            gate = edge.get("gate", {})
            gate_type = gate.get("type", "?")
            gate_file = gate.get("file", "")
            gate_desc = gate.get("description", "")
            threshold = gate.get("threshold")
            gate_str = "%s %s" % (gate_type, gate_file)
            if threshold:
                gate_str += " (threshold=%s)" % threshold
            if gate_desc:
                gate_str += " — %s" % gate_desc
            parts.append("     Gate to next: %s" % gate_str)

        parts.append("")

    # Template placeholders
    placeholders = graph.get("template_placeholders", {})
    if placeholders:
        parts.append("Template placeholders to fill:")
        for name, desc in placeholders.items():
            parts.append("  %s: %s" % (name, desc))
        parts.append("")

    parts.append("=== END WORKFLOW GRAPH ===")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Gap parsing
# ═══════════════════════════════════════════════════════════════════════

def _parse_gaps(raw: str) -> List[Dict[str, str]]:
    """Parse LLM audit output into gap records."""
    gaps = []

    if "=== NO_GAPS ===" in raw:
        return gaps

    parts = re.split(r"^=== GAP:\s*(.+?)\s*===\s*$", raw, flags=re.MULTILINE)
    i = 1
    while i < len(parts) - 1:
        name = parts[i]
        content = parts[i + 1].strip()

        gap = {"name": name}
        for line in content.splitlines():
            line = line.strip()
            for field in ("Type", "Referenced_by", "Description", "Severity", "Question"):
                if line.lower().startswith(field.lower() + ":"):
                    gap[field.lower()] = line.split(":", 1)[1].strip()

        gaps.append(gap)
        i += 2

    return gaps


# ═══════════════════════════════════════════════════════════════════════
# Catalog I/O
# ═══════════════════════════════════════════════════════════════════════

def load_catalog(plugins_root: Path) -> Dict[str, Any]:
    """Load the catalog from _catalog.yaml."""
    catalog_path = plugins_root / _CATALOG_FILENAME
    if catalog_path.exists():
        try:
            data = yaml.safe_load(catalog_path.read_text())
            return data if isinstance(data, dict) else {"plugins": {}}
        except Exception:
            return {"plugins": {}}
    return {"plugins": {}}


def save_catalog(plugins_root: Path, catalog: Dict[str, Any]) -> Path:
    """Save the catalog to _catalog.yaml."""
    catalog_path = plugins_root / _CATALOG_FILENAME
    catalog_path.write_text(
        yaml.dump(catalog, default_flow_style=False, sort_keys=False, width=120),
        encoding="utf-8",
    )
    return catalog_path


# ═══════════════════════════════════════════════════════════════════════
# Cross-reference with existing catalog
# ═══════════════════════════════════════════════════════════════════════

def _cross_reference(
    plugin_dir: Path,
    plugin_files: Set[str],
    catalog: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    Compare the new plugin against already-cataloged plugins.
    Returns suggestions about potentially missing files.
    """
    suggestions = []
    plugin_name = plugin_dir.name

    for cat_name, cat_entry in catalog.get("plugins", {}).items():
        if cat_name == plugin_name:
            continue

        cat_files = cat_entry.get("files", {})
        if not cat_files:
            continue

        # Count how many files overlap (by role, not name)
        cat_roles = {f: info.get("role", "") for f, info in cat_files.items()}
        my_roles = {}
        for f in plugin_files:
            # Guess role from filename
            if any(kw in f.lower() for kw in ("run_", "driver", "compute")):
                my_roles[f] = "driver"
            elif any(kw in f.lower() for kw in ("start", "launch", "main")):
                my_roles[f] = "entry_point"
            elif any(kw in f.lower() for kw in ("monitor", "health", "backup", "status")):
                my_roles[f] = "operational"
            elif f.endswith(".submit"):
                my_roles[f] = "config"

        # Check if this cataloged plugin is similar enough to compare
        shared_roles = set(my_roles.values()) & set(cat_roles.values())
        if len(shared_roles) < 2:
            continue  # Not similar enough

        # Find roles present in catalog but missing from our plugin
        cat_role_set = set(cat_roles.values())
        my_role_set = set(my_roles.values())

        for cat_file, cat_role in cat_roles.items():
            if cat_role not in my_role_set and cat_role != "adapter":
                desc = cat_files[cat_file].get("description", "")
                suggestions.append({
                    "reference_plugin": cat_name,
                    "missing_role": cat_role,
                    "example_file": cat_file,
                    "description": desc,
                })

    return suggestions


# ═══════════════════════════════════════════════════════════════════════
# Build the full scan/content for LLM prompts
# ═══════════════════════════════════════════════════════════════════════

def _build_plugin_content(plugin_dir: Path) -> Tuple[str, Set[str]]:
    """Read all plugin files, return (prompt_content, set_of_filenames)."""
    from .ignore import load_ignore_patterns, should_ignore

    parts = []
    all_files = set()
    patterns = load_ignore_patterns(plugin_dir)

    # README
    for name in ("README.md", "WORKFLOW.md", "README.txt"):
        rp = plugin_dir / name
        if rp.exists():
            content = rp.read_text(errors="ignore")[:_MAX_SCRIPT_CHARS]
            parts.append(f"=== {name} ===\n{content}\n=== END ===\n")
            all_files.add(name)

    # plugin.yaml
    manifest_path = plugin_dir / "plugin.yaml"
    if manifest_path.exists():
        parts.append(f"=== plugin.yaml ===\n{manifest_path.read_text(errors='ignore')}\n=== END ===\n")
        all_files.add("plugin.yaml")

    # All scripts (in root and subdirs, filtered by .golddigrignore)
    script_exts = (".sh", ".py", ".bash", ".submit", ".r", ".R")
    for f in sorted(plugin_dir.rglob("*")):
        if f.is_file() and f.suffix in script_exts:
            if should_ignore(f, plugin_dir, patterns):
                continue
            rel = str(f.relative_to(plugin_dir))
            if ".bak" in rel:
                continue
            content = f.read_text(errors="ignore")[:_MAX_SCRIPT_CHARS]
            parts.append(f"=== SCRIPT: {rel} ===\n{content}\n=== END ===\n")
            all_files.add(f.name)
            all_files.add(rel)

    # Templates
    for f in sorted(plugin_dir.rglob("*.template")) + sorted(plugin_dir.rglob("*.inp")):
        if should_ignore(f, plugin_dir, patterns):
            continue
        rel = str(f.relative_to(plugin_dir))
        if ".bak" in rel:
            continue
        content = f.read_text(errors="ignore")[:5000]
        parts.append(f"=== TEMPLATE: {rel} ===\n{content}\n=== END ===\n")
        all_files.add(f.name)
        all_files.add(rel)

    # Config files
    for name in ("environment.yml", "environment.yaml", "cluster.yaml", "cluster.env",
                  "config.txt", ".golddigrignore"):
        fp = plugin_dir / name
        if fp.exists():
            parts.append(f"=== CONFIG: {name} ===\n{fp.read_text(errors='ignore')[:3000]}\n=== END ===\n")
            all_files.add(name)

    # Diagnosis history (if present)
    for hist_name in ("diagnosis_report.md", "autofix_report.json"):
        for hp in plugin_dir.rglob(hist_name):
            if should_ignore(hp, plugin_dir, patterns):
                continue
            content = hp.read_text(errors="ignore")[:5000]
            parts.append(f"=== HISTORY: {hist_name} ===\n{content}\n=== END ===\n")
            break

    # Show what was ignored (for transparency)
    ignored_count = 0
    for f in plugin_dir.rglob("*"):
        if f.is_file() and should_ignore(f, plugin_dir, patterns):
            ignored_count += 1
    if ignored_count > 0:
        parts.append(f"\n(Note: {ignored_count} file(s) skipped by .golddigrignore)\n")

    return "\n".join(parts), all_files




# ═══════════════════════════════════════════════════════════════════════
# Main catalog function
# ═══════════════════════════════════════════════════════════════════════

def catalog_plugin(
    plugin_dir: Path,
    plugins_root: Path,
    provider: str = "openai",
    model: str = "gpt-4o",
    non_interactive: bool = False,
) -> bool:
    """
    Validate and catalog a plugin into _catalog.yaml.

    Three phases:
      1. Static scan — find missing file references
      2. LLM audit — check workflow completeness
      3. Cross-reference — compare with cataloged plugins

    Only catalogs if all critical gaps are resolved.
    Returns True if catalog entry was written.
    """
    plugin_dir = Path(plugin_dir).resolve()

    if not plugin_dir.is_dir():
        print(f"❌ Not a directory: {plugin_dir}")
        return False

    plugin_name = None
    manifest_path = plugin_dir / "plugin.yaml"
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text())
            plugin_name = manifest.get("name")
        except Exception:
            pass
    if not plugin_name:
        plugin_name = plugin_dir.name

    print(f"\n📚 Cataloging plugin: {plugin_name}")
    print(f"   Directory: {plugin_dir}\n")

    # Load existing catalog
    catalog = load_catalog(plugins_root)
    if plugin_name in catalog.get("plugins", {}):
        print(f"   ⚠ Plugin '{plugin_name}' is already cataloged.")
        if not non_interactive and not confirm("Re-catalog (overwrite existing entry)?"):
            return False

    # ── Phase 1: Static reference scan ────────────────────────────────
    print("🔗 Phase 1: Static reference scan...\n")

    refs = _scan_references(plugin_dir)
    missing_refs = [r for r in refs if not r["exists"]]

    if missing_refs:
        print(f"   Found {len(missing_refs)} missing reference(s):\n")
        for ref in missing_refs:
            print(f"   ⚠ {ref['source_file']} (line {ref['line_num']}): "
                  f"{ref['type']} → {ref['reference']}")
    else:
        print("   ✅ All file references resolved.\n")

    # ── Phase 2: LLM workflow audit ───────────────────────────────────
    print("🤖 Phase 2: LLM workflow audit...\n")

    plugin_content, all_files = _build_plugin_content(plugin_dir)

    # Include static scan results in audit prompt
    audit_parts = [plugin_content]
    if missing_refs:
        audit_parts.append("=== STATIC SCAN: MISSING REFERENCES ===")
        for ref in missing_refs:
            audit_parts.append(
                f"  {ref['source_file']} line {ref['line_num']}: "
                f"{ref['type']} → {ref['reference']} (NOT FOUND)"
            )
        audit_parts.append("=== END STATIC SCAN ===\n")

    audit_parts.append(
        "Audit this plugin for completeness. Identify any gaps that would "
        "prevent the workflow from running end-to-end.\n"
    )

    try:
        raw_audit = call_llm(provider, model, _AUDIT_SYSTEM, "\n".join(audit_parts), 0.2)
    except Exception as e:
        logger.error("LLM API error during audit: %s", e)
        print(f"❌ LLM API error: {e}")
        return False

    gaps = _parse_gaps(raw_audit)

    # ── Phase 3: Cross-reference with catalog ─────────────────────────
    print("📚 Phase 3: Cross-reference with existing catalog...\n")

    xref_suggestions = _cross_reference(plugin_dir, all_files, catalog)

    # ── Present all findings ──────────────────────────────────────────
    all_issues = []

    # From LLM audit
    for gap in gaps:
        all_issues.append({
            "source": "llm_audit",
            "name": gap.get("name", "?"),
            "severity": gap.get("severity", "warning"),
            "description": gap.get("description", ""),
            "question": gap.get("question", ""),
            "type": gap.get("type", "unknown"),
        })

    # From cross-reference (as warnings)
    for sug in xref_suggestions:
        all_issues.append({
            "source": "cross_reference",
            "name": f"Missing {sug['missing_role']} (vs {sug['reference_plugin']})",
            "severity": "warning",
            "description": (
                f"Plugin '{sug['reference_plugin']}' has a {sug['missing_role']} script "
                f"({sug['example_file']}): {sug['description']}. "
                f"Your plugin doesn't have an equivalent."
            ),
            "question": f"Is a {sug['missing_role']} script needed for your workflow?",
            "type": "missing_file",
        })

    # From static scan (critical)
    for ref in missing_refs:
        # Don't duplicate if LLM already caught it
        if not any(ref["reference"] in issue.get("name", "") for issue in all_issues):
            all_issues.append({
                "source": "static_scan",
                "name": ref["reference"],
                "severity": "critical",
                "description": (
                    f"Referenced in {ref['source_file']} (line {ref['line_num']}) "
                    f"as {ref['type']}, but file not found."
                ),
                "question": f"Where is {ref['reference']}? Is it missing or handled differently?",
                "type": "missing_file",
            })

    # ── Show issues and resolve ───────────────────────────────────────
    critical = [i for i in all_issues if i["severity"] == "critical"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]

    if not all_issues:
        print("   ✅ No gaps found! Plugin appears complete.\n")
    else:
        if critical:
            print(f"   🔴 {len(critical)} critical gap(s):\n")
            for i, issue in enumerate(critical, 1):
                print(f"   {i}. {issue['name']}")
                print(f"      {issue['description']}")
                if not non_interactive and issue.get("question"):
                    answer = ask_user(f"      {issue['question']}")
                    issue["resolution"] = answer
                print()

        if warnings:
            print(f"   🟡 {len(warnings)} warning(s):\n")
            for i, issue in enumerate(warnings, 1):
                print(f"   {i}. {issue['name']}")
                print(f"      {issue['description']}")
                if not non_interactive and issue.get("question"):
                    answer = ask_user(f"      {issue['question']}")
                    issue["resolution"] = answer
                print()

    # Check for unresolved critical issues
    unresolved_critical = [
        i for i in critical
        if not i.get("resolution") or i["resolution"].strip() == ""
    ]

    if unresolved_critical and not non_interactive:
        print(f"   ❌ {len(unresolved_critical)} critical gap(s) unresolved.")
        print(f"   Please provide the missing files and re-run catalog.\n")
        if not confirm("Catalog anyway (entry will be marked incomplete)?"):
            return False

    # ── Phase 4: Sample file collection ───────────────────────────────
    print("📄 Phase 4: Sample input files...\n")

    sample_info = []
    sample_prompt = ""
    try:
        from .samples import collect_samples_interactive, format_samples_for_prompt
        sample_info = collect_samples_interactive(plugin_dir, non_interactive=non_interactive)
        if sample_info:
            sample_prompt = format_samples_for_prompt(sample_info)
            print(f"\n   ✅ {len(sample_info)} sample(s) inspected")
        else:
            print("   ℹ No samples — adapter generation will rely on script analysis only")
    except Exception as e:
        logger.debug("Sample collection failed: %s", e)
    print()

    # ── Phase 5: Container interface detection ────────────────────────
    print("🐳 Phase 5: Container interface detection...\n")

    container_context = ""
    try:
        from .containers import detect_container_usage, generate_containers_yaml, format_containers_for_prompt
        detections = detect_container_usage(plugin_dir)

        if detections:
            print(f"   Found {len(detections)} container invocation(s):\n")
            for d in detections:
                print(f"   🐳 {d.get('image', '?')}")
                print(f"      Runtime: {d.get('runtime', '?')}")
                print(f"      In: {d.get('source_file', '?')} (line {d.get('line_num', '?')})")
                if d.get("executables"):
                    print(f"      Executables: {', '.join(d['executables'][:5])}")
                if d.get("bind_mounts"):
                    print(f"      Bind mounts: {', '.join(d['bind_mounts'])}")
                if d.get("environment"):
                    for k, v in list(d["environment"].items())[:3]:
                        print(f"      Env: {k}={v}")
                if d.get("file_inputs"):
                    print(f"      Inputs: {', '.join(d['file_inputs'][:5])}")
                if d.get("file_outputs"):
                    print(f"      Outputs: {', '.join(d['file_outputs'][:5])}")
                print()

            # Generate containers.yaml
            yaml_path = generate_containers_yaml(plugin_dir, detections)
            print(f"   📄 Saved: {yaml_path}")

            # Format for LLM prompt
            container_context = format_containers_for_prompt(detections)
        else:
            print("   ℹ No container invocations detected in scripts.")
    except Exception as e:
        logger.debug("Container detection failed: %s", e)
    print()

    # ── Workflow graph extraction ────────────────────────────────────
    print("🔀 Extracting workflow graph...\n")
    workflow_graph = None
    try:
        from .initializer import scan_plugin_dir
        wg_scan = scan_plugin_dir(plugin_dir)
        workflow_graph = extract_workflow_graph(plugin_dir, wg_scan, provider, model)
        if workflow_graph:
            n_nodes = len(workflow_graph.get("nodes", []))
            n_edges = len(workflow_graph.get("edges", []))
            entry_pt = workflow_graph.get("entry_point", "?")
            print(f"   ✅ Extracted graph: {n_nodes} stages, {n_edges} transitions")
            print(f"   Entry point: {entry_pt}")
            for node in workflow_graph.get("nodes", []):
                print(f"   • {node.get('id', '?')} [{node.get('type', '?')}]")
        else:
            print("   ⚠  Could not extract workflow graph (non-critical)")
    except Exception as e:
        logger.debug("Workflow graph extraction failed: %s", e)
        print(f"   ⚠  Graph extraction failed: {e}")
    print()

    # ── Generate catalog entry via LLM ────────────────────────────────
    print("📝 Generating catalog entry...\n")

    # Add resolution info to the prompt
    catalog_parts = [plugin_content]

    if all_issues:
        catalog_parts.append("=== GAP RESOLUTION NOTES ===")
        for issue in all_issues:
            resolution = issue.get("resolution", "")
            catalog_parts.append(
                f"  {issue['name']} ({issue['severity']}): {issue['description']}"
            )
            if resolution:
                catalog_parts.append(f"    User says: {resolution}")
        catalog_parts.append("=== END NOTES ===\n")

    # Include diagnosis history from pilot dirs if available
    pilots_dir = plugins_root.parent / "data" / "output" / "pilots" / plugin_name
    if not pilots_dir.is_dir():
        # Try CWD-relative
        pilots_dir = Path("data") / "output" / "pilots" / plugin_name

    if pilots_dir.is_dir():
        for report_file in pilots_dir.rglob("diagnosis_report.md"):
            content = report_file.read_text(errors="ignore")[:3000]
            catalog_parts.append(f"=== DIAGNOSIS HISTORY ===\n{content}\n=== END ===\n")
            break
        for fix_file in pilots_dir.rglob("autofix_report.json"):
            content = fix_file.read_text(errors="ignore")[:3000]
            catalog_parts.append(f"=== FIX HISTORY ===\n{content}\n=== END ===\n")
            break
        for fix_hist in pilots_dir.rglob("fix_history.json"):
            content = fix_hist.read_text(errors="ignore")[:3000]
            catalog_parts.append(f"=== FIX ITERATION HISTORY ===\n{content}\n=== END ===\n")
            break

    # NOTE: No infrastructure probe here. Catalog records the infrastructure
    # the plugin was DESIGNED for (inferred from scripts), not the current machine.
    # The probe is used by init/port where the target machine matters.

    # Include sample file inspections
    if sample_prompt:
        catalog_parts.append(sample_prompt + "\n")
        print("   📄 Sample file info included")

    # Include container interface info
    if container_context:
        catalog_parts.append(container_context + "\n")
        print("   🐳 Container interface info included")

    catalog_parts.append(
        "Generate a catalog entry for this plugin as raw YAML.\n"
        "Include all files, concepts, patterns, known issues, AND infrastructure.\n"
        "For the infrastructure section, infer from the scripts (scheduler commands,\n"
        "container invocations, filesystem paths, MPI usage).\n"
        "If containers were detected, include container_interface in the entry.\n"
        "Output ONLY raw YAML, no fences, no explanation.\n"
    )

    try:
        raw_entry = call_llm(provider, model, _CATALOG_SYSTEM, "\n".join(catalog_parts), 0.2)
    except Exception as e:
        logger.error("LLM API error during cataloging: %s", e)
        print(f"❌ LLM API error: {e}")
        return False

    # Clean YAML
    raw_entry = raw_entry.strip()
    if raw_entry.startswith("```"):
        raw_entry = re.sub(r"^```\w*\n?", "", raw_entry)
        raw_entry = re.sub(r"\n?```$", "", raw_entry)

    # Validate YAML
    try:
        entry = yaml.safe_load(raw_entry)
        if not isinstance(entry, dict):
            print("⚠  LLM returned non-dict YAML. Saving raw text.")
            entry = {"raw": raw_entry}
    except yaml.YAMLError as e:
        logger.warning("YAML parse error in catalog entry: %s", e)
        print(f"⚠  YAML parse error: {e}")
        # Try to fix common issues
        fixed = fix_yaml_quoting(raw_entry)
        try:
            entry = yaml.safe_load(fixed)
        except yaml.YAMLError:
            print("   Could not fix. Saving raw text.")
            entry = {"raw": raw_entry}

    # Attach workflow graph if extracted
    if workflow_graph:
        entry["workflow_graph"] = workflow_graph

    # Mark completeness
    if unresolved_critical:
        entry["_status"] = "incomplete"
        entry["_unresolved"] = [i["name"] for i in unresolved_critical]
    else:
        entry["_status"] = "complete"

    # ── Show and confirm ──────────────────────────────────────────────
    print("═" * 60)
    print(yaml.dump({plugin_name: entry}, default_flow_style=False, sort_keys=False, width=100))
    print("═" * 60)

    if not non_interactive:
        if not confirm("Save this catalog entry?"):
            return False

    # ── Save to catalog ───────────────────────────────────────────────
    if "plugins" not in catalog:
        catalog["plugins"] = {}

    catalog["plugins"][plugin_name] = entry
    catalog_path = save_catalog(plugins_root, catalog)

    print(f"\n✅ Cataloged '{plugin_name}' → {catalog_path}")
    print(f"   Status: {entry.get('_status', 'unknown')}")
    print(f"   Total plugins in catalog: {len(catalog['plugins'])}")

    return True




# ═══════════════════════════════════════════════════════════════════════
# Snippet extraction — Two-call approach
#   Call 1: Blind extraction (no library context, no self-censoring)
#   Call 2: Match extracted concepts against existing library (cheap, metadata only)
# ═══════════════════════════════════════════════════════════════════════

_EXTRACT_SYSTEM = """\
You are a code architect extracting reusable, tested building blocks from \
a working computational workflow.

Your job: identify every COMPOSABLE BLOCK and extract it as a standalone snippet.

WHAT TO EXTRACT:
1. SUBMISSION: job submission, queue throttling, chunk management
2. TASK WRAPPER: per-job execution on compute node
3. HEALTH MONITOR: detect failed/held jobs, auto-heal, escalate resources
4. RESULT BACKUP: verified archival, manifests
5. SCIENCE INPUT: tool-specific input templates (.inp, .com, etc.)
6. SCIENCE DRIVER: tool invocation with error handling
7. ADAPTER: data format transformation
8. WATCHDOG: wall-time management, graceful kill, partial results
9. ROUND2: resume/resubmission from partial results
10. STATUS: operational dashboard
11. CONTAINER WRAPPER: container invocation with bind mounts and env setup
12. CHARGE/MULT: electron counting, multiplicity determination

RULES:
- SINGLE RESPONSIBILITY: each concept does ONE thing. A 200-line script that \
  does ORCA + Multiwfn + watchdog + status + packing is FIVE concepts, not one. \
  If a block is over 80 lines, consider splitting.
- SELF-CONTAINED: each snippet must be runnable with the right inputs
- Keep TESTED code — don't refactor or "improve"
- Use {{DOUBLE_BRACE}} placeholders for workflow-specific values
- INVARIANTS are the most valuable part — encode hard-won lessons
- Name concepts by FUNCTION (submission, health_monitor, orca_input)

OUTPUT FORMAT:
For each concept:

=== CONCEPT: short_name ===
Description: One-line description
Category: scheduler | science | compute | adapters | monitoring
Invariants:
  - "Rule that must be preserved in any adaptation"
Interface_inputs: VAR1, VAR2, VAR3
Interface_outputs: output_description
Scheduler: sge | slurm | htcondor | pbs | any
Tool: orca | gaussian | multiwfn | xtb | pytorch | any
Infrastructure: shared_fs | isolated | htcondor_transfer
Tested_by: plugin_name
Notes: usage notes

```
(actual file content with {{PLACEHOLDER}} variables)
```

=== END CONCEPT ===
"""


_MATCH_SYSTEM = """\
You are matching newly extracted code concepts against an existing library \
to decide which are new and which are variants of existing concepts.

You will receive:
- LIST A: concepts just extracted from a new plugin (name + description + interface)
- LIST B: concepts already in the library (name + description + invariants + existing variants)

For EACH concept in List A, decide:
  MATCH → it does the same thing as a concept in List B (even if implementation differs)
  NEW   → it's a genuinely novel pattern not in List B

Output format:

=== MATCH: extracted_name → library_name ===
Variant_name: descriptive_name_for_this_variant
Reason: Why this is the same concept (one line)
=== END MATCH ===

=== NEW: extracted_name ===
Reason: Why this doesn't match anything in the library (one line)
=== END NEW ===

RULES:
- Same FUNCTION = match, even if different scheduler/tool/language
  (e.g., "SGE array submit" matches "HTCondor chunked submit" — both are "submission")
- Different function = new, even if similar implementation
  (e.g., "backup results" ≠ "submit jobs" even if both use tar)
- You MUST address every concept in List A — no silent skips
- When in doubt, MATCH rather than NEW (variants are cheap, duplicate concepts are expensive)
"""


def _parse_blind_extraction(raw: str) -> List[Dict[str, Any]]:
    """Parse Call 1 output: list of concepts with code."""
    concepts = []

    parts = re.split(r'^=== CONCEPT:\s*(.+?)\s*===\s*$', raw, flags=re.MULTILINE)

    i = 1
    while i < len(parts) - 1:
        name = parts[i].strip()
        block = parts[i + 1]

        end_idx = block.find("=== END CONCEPT ===")
        if end_idx >= 0:
            block = block[:end_idx]

        concept: Dict[str, Any] = {"name": name}
        invariants = []

        for line in block.splitlines():
            s = line.strip()
            if s.startswith("Description:"):
                concept["description"] = s.split(":", 1)[1].strip()
            elif s.startswith("Category:"):
                concept["category"] = s.split(":", 1)[1].strip()
            elif s.startswith("Interface_inputs:"):
                concept["inputs"] = [v.strip() for v in s.split(":", 1)[1].split(",") if v.strip()]
            elif s.startswith("Interface_outputs:"):
                concept["outputs"] = [v.strip() for v in s.split(":", 1)[1].split(",") if v.strip()]
            elif s.startswith("Scheduler:"):
                concept["scheduler"] = s.split(":", 1)[1].strip()
            elif s.startswith("Tool:"):
                concept["tool"] = s.split(":", 1)[1].strip()
            elif s.startswith("Infrastructure:"):
                concept["infrastructure"] = s.split(":", 1)[1].strip()
            elif s.startswith("Tested_by:"):
                concept["tested_by"] = [v.strip() for v in s.split(":", 1)[1].split(",") if v.strip()]
            elif s.startswith("Notes:"):
                concept["notes"] = s.split(":", 1)[1].strip()
            elif s.startswith('- "') or s.startswith("- '"):
                inv = s.lstrip("- ").strip("\"'")
                if inv:
                    invariants.append(inv)

        concept["invariants"] = invariants

        # Extract code
        code_match = re.search(r'```\w*\n(.*?)```', block, re.DOTALL)
        if code_match:
            concept["code"] = code_match.group(1).strip() + "\n"
        else:
            code_lines = []
            in_code = False
            for line in block.splitlines():
                s = line.strip()
                if not in_code and s.startswith(("#!/", "import ", "!", "%", "from ", "set -")):
                    in_code = True
                if in_code:
                    code_lines.append(line)
            if code_lines:
                concept["code"] = "\n".join(code_lines).strip() + "\n"

        if concept.get("code"):
            concepts.append(concept)

        i += 2

    return concepts


def _parse_match_results(raw: str) -> Dict[str, Dict[str, str]]:
    """
    Parse Call 2 output: mapping of extracted concept → match/new decision.

    Returns: {
        "extracted_name": {"action": "match", "library_name": "...", "variant_name": "..."},
        "extracted_name2": {"action": "new"},
    }
    """
    decisions: Dict[str, Dict[str, str]] = {}

    # Parse MATCH blocks
    for m in re.finditer(
        r'^=== MATCH:\s*(.+?)\s*→\s*(.+?)\s*===\s*$(.+?)^=== END MATCH ===',
        raw, re.MULTILINE | re.DOTALL,
    ):
        extracted = m.group(1).strip()
        library = m.group(2).strip()
        block = m.group(3)

        variant_name = ""
        reason = ""
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("Variant_name:"):
                variant_name = s.split(":", 1)[1].strip()
            elif s.startswith("Reason:"):
                reason = s.split(":", 1)[1].strip()

        decisions[extracted] = {
            "action": "match",
            "library_name": library,
            "variant_name": variant_name,
            "reason": reason,
        }

    # Parse NEW blocks
    for m in re.finditer(
        r'^=== NEW:\s*(.+?)\s*===\s*$(.+?)^=== END NEW ===',
        raw, re.MULTILINE | re.DOTALL,
    ):
        extracted = m.group(1).strip()
        block = m.group(2)
        reason = ""
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("Reason:"):
                reason = s.split(":", 1)[1].strip()

        decisions[extracted] = {"action": "new", "reason": reason}

    return decisions


def _build_match_prompt(
    extracted: List[Dict[str, Any]],
    plugins_root: Path,
) -> str:
    """Build the matching prompt with List A (extracted) and List B (library)."""
    from .library import load_index, load_concept

    parts = ["=== LIST A: Newly extracted concepts ===\n"]
    for i, c in enumerate(extracted, 1):
        parts.append(f"{i}. {c['name']}")
        parts.append(f"   Description: {c.get('description', '')}")
        parts.append(f"   Category: {c.get('category', '?')}")
        if c.get("inputs"):
            parts.append(f"   Inputs: {', '.join(c['inputs'])}")
        if c.get("outputs"):
            parts.append(f"   Outputs: {', '.join(c['outputs'])}")
        parts.append(f"   Scheduler: {c.get('scheduler', 'any')}")
        parts.append(f"   Tool: {c.get('tool', 'any')}")
        parts.append("")
    parts.append("=== END LIST A ===\n")

    index = load_index(plugins_root)
    existing = index.get("concepts", {})

    if not existing:
        parts.append("=== LIST B: (empty — no existing concepts) ===")
        parts.append("All concepts in List A are NEW.")
        return "\n".join(parts)

    parts.append(f"=== LIST B: Existing library ({len(existing)} concepts) ===\n")
    for i, cname in enumerate(existing, 1):
        concept = load_concept(plugins_root, cname)
        if not concept:
            continue
        variants = list(concept.get("variants", {}).keys())
        parts.append(f"{i}. {cname}")
        parts.append(f"   Description: {concept.get('description', '')}")
        parts.append(f"   Category: {concept.get('category', '?')}")
        if concept.get("invariants"):
            for inv in concept["invariants"][:3]:
                parts.append(f"   Invariant: {inv}")
        parts.append(f"   Variants: {', '.join(variants) if variants else 'none'}")
        parts.append("")
    parts.append("=== END LIST B ===\n")

    parts.append(
        "For EACH concept in List A, output MATCH or NEW.\n"
        "Remember: same function = MATCH even if different scheduler/tool.\n"
    )

    return "\n".join(parts)


def extract_snippets(
    plugin_dir: Path,
    plugins_root: Path,
    provider: str = "openai",
    model: str = "gpt-4o",
    non_interactive: bool = False,
) -> List[str]:
    """
    Two-call extraction:
      Call 1: Blind extraction (no library context → no self-censoring)
      Call 2: Match extracted concepts against library (cheap, metadata only)
    """
    from .library import (
        get_library_path, load_index, load_concept,
        save_concept, save_variant,
    )

    plugin_dir = Path(plugin_dir).resolve()
    plugin_name = plugin_dir.name

    manifest_path = plugin_dir / "plugin.yaml"
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text())
            plugin_name = manifest.get("name", plugin_name)
        except Exception:
            pass

    print(f"\n🔬 Extracting concepts from: {plugin_name}\n")

    # ── Call 1: Blind extraction ──────────────────────────────────────
    print("   📝 Call 1: Blind extraction (no library context)...")

    plugin_content, _ = _build_plugin_content(plugin_dir)

    catalog = load_catalog(plugins_root)
    cat_entry = catalog.get("plugins", {}).get(plugin_name, {})
    if cat_entry:
        plugin_content += f"\n=== CATALOG ENTRY ===\n"
        plugin_content += yaml.dump(cat_entry, default_flow_style=False, sort_keys=False, width=120)
        plugin_content += "=== END CATALOG ===\n"

    plugin_content += "\nExtract all reusable concepts from this plugin.\n"

    try:
        raw_extract = call_llm(provider, model, _EXTRACT_SYSTEM, plugin_content, 0.2)
    except Exception as e:
        logger.error("LLM API error during snippet extraction: %s", e)
        print(f"❌ LLM API error (extraction): {e}")
        return []

    # Save raw
    debug_path = get_library_path(plugins_root) / f"extract_raw_{plugin_name}.txt"
    debug_path.write_text(raw_extract, encoding="utf-8")

    extracted = _parse_blind_extraction(raw_extract)

    if not extracted:
        print("⚠  No concepts extracted.")
        return []

    print(f"   ✅ Extracted {len(extracted)} concept(s)")
    for c in extracted:
        print(f"      {c['name']}: {c.get('description', '')[:60]}")

    # ── Call 2: Match against library ─────────────────────────────────
    n_existing = len(load_index(plugins_root).get("concepts", {}))

    if n_existing > 0:
        print(f"\n   🔄 Call 2: Matching against {n_existing} existing concept(s)...")

        match_prompt = _build_match_prompt(extracted, plugins_root)

        try:
            raw_match = call_llm(provider, model, _MATCH_SYSTEM, match_prompt, 0.1)
        except Exception as e:
            logger.error("LLM API error during concept matching: %s", e)
            print(f"❌ LLM API error (matching): {e}")
            # Fall through — treat everything as new
            raw_match = ""

        # Save raw
        (get_library_path(plugins_root) / f"match_raw_{plugin_name}.txt").write_text(
            raw_match, encoding="utf-8"
        )

        decisions = _parse_match_results(raw_match)
        print(f"   ✅ Matching complete")
    else:
        print(f"\n   📋 Empty library — all concepts are new")
        decisions = {c["name"]: {"action": "new"} for c in extracted}

    # ── Show results ──────────────────────────────────────────────────
    matches = [(c, decisions.get(c["name"], {})) for c in extracted
               if decisions.get(c["name"], {}).get("action") == "match"]
    news = [(c, decisions.get(c["name"], {})) for c in extracted
            if decisions.get(c["name"], {}).get("action") != "match"]

    print(f"\n📦 Results: {len(matches)} variant(s), {len(news)} new concept(s)\n")

    saved = []

    # ── Process matches (add as variant to existing concept) ──────────
    if matches:
        print("🔄 Variants for existing concepts:\n")

    for concept, decision in matches:
        cname = concept["name"]
        lib_name = decision.get("library_name", cname)
        vname = decision.get("variant_name", f"{plugin_name}_default")
        reason = decision.get("reason", "")
        code = concept.get("code", "")
        code_lines = code.count("\n")

        existing = load_concept(plugins_root, lib_name)
        existing_vars = list(existing.get("variants", {}).keys()) if existing else []

        print(f"   🔄 {cname} → {lib_name} (variant: {vname})")
        print(f"      {reason}")
        print(f"      {code_lines} lines  |  Existing: {', '.join(existing_vars)}")

        if not non_interactive:
            if not confirm(f"      Save variant?"):
                continue

        header = _build_snippet_header(lib_name, vname, concept, [], plugin_name)
        full_code = header + code if "── SNIPPET:" not in code else code

        # Merge invariants
        if existing:
            merged_inv = list(set(
                existing.get("invariants", []) + concept.get("invariants", [])
            ))
            existing["invariants"] = merged_inv
            save_concept(plugins_root, lib_name, existing)

        variant_meta = {
            "scheduler": concept.get("scheduler", "any"),
            "tool": concept.get("tool", "any"),
            "infrastructure": {"filesystem": concept.get("infrastructure", "unknown")},
            "tested_by": concept.get("tested_by", [plugin_name]),
        }
        if concept.get("notes"):
            variant_meta["notes"] = concept["notes"]

        filepath = save_variant(plugins_root, lib_name, vname, full_code, variant_meta)
        print(f"      ✅ Saved: {filepath}")
        saved.append(f"{lib_name}/{vname}")

    # ── Process new concepts ──────────────────────────────────────────
    if news:
        print("\n🆕 New concepts:\n")

    for concept, decision in news:
        cname = concept["name"]
        desc = concept.get("description", "")
        category = concept.get("category", "monitoring")
        invariants = concept.get("invariants", [])
        code = concept.get("code", "")
        vname = f"{plugin_name}_default"
        code_lines = code.count("\n")

        print(f"   📝 {cname}")
        print(f"      {desc}")
        print(f"      Category: {category}  |  {code_lines} lines")
        if invariants:
            for inv in invariants[:3]:
                print(f"      • {inv[:80]}")

        # Check if it accidentally matches an existing concept name
        existing = load_concept(plugins_root, cname)
        if existing:
            print(f"      ℹ Concept '{cname}' exists — adding as variant instead")

        if not non_interactive:
            if not confirm(f"      Save?"):
                continue

        header = _build_snippet_header(cname, vname, concept, invariants, plugin_name)
        full_code = header + code if "── SNIPPET:" not in code else code

        if not existing:
            save_concept(plugins_root, cname, {
                "name": cname,
                "description": desc,
                "category": category,
                "interface": {
                    "inputs": concept.get("inputs", []),
                    "outputs": concept.get("outputs", []),
                },
                "invariants": invariants,
                "variants": {},
            })
        else:
            merged_inv = list(set(existing.get("invariants", []) + invariants))
            existing["invariants"] = merged_inv
            if desc and not existing.get("description"):
                existing["description"] = desc
            save_concept(plugins_root, cname, existing)

        variant_meta = {
            "scheduler": concept.get("scheduler", "any"),
            "tool": concept.get("tool", "any"),
            "infrastructure": {"filesystem": concept.get("infrastructure", "unknown")},
            "tested_by": concept.get("tested_by", [plugin_name]),
        }
        if concept.get("notes"):
            variant_meta["notes"] = concept["notes"]

        filepath = save_variant(plugins_root, cname, vname, full_code, variant_meta)
        print(f"      ✅ Saved: {filepath}")
        saved.append(f"{cname}/{vname}")

    # Summary
    lib_path = get_library_path(plugins_root)
    total_concepts = len(load_index(plugins_root).get("concepts", {}))
    print(f"\n✅ {len(saved)} concept/variant(s) saved to {lib_path}")
    print(f"   Total concepts in library: {total_concepts}")

    return saved


def _build_snippet_header(
    cname: str, vname: str, concept: Dict, invariants: List[str], plugin_name: str,
) -> str:
    """Build a standard header for snippet files."""
    header = (
        f"# ── SNIPPET: {cname}/{vname} "
        + "─" * max(1, 45 - len(cname) - len(vname)) + "\n"
    )
    if concept.get("scheduler"):
        header += f"# Scheduler:   {concept['scheduler']}\n"
    if concept.get("tool"):
        header += f"# Tool:        {concept['tool']}\n"
    header += f"# Tested:      {', '.join(concept.get('tested_by', [plugin_name]))}\n"
    if invariants:
        header += "# Invariants:\n"
        for inv in invariants:
            header += f"#   - {inv}\n"
    if concept.get("notes"):
        header += f"# Notes: {concept['notes']}\n"
    header += "# " + "─" * 60 + "\n\n"
    return header
