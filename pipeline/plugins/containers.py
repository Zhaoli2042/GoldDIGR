"""
pipeline.plugins.containers – Container interface detection and documentation.

Scans plugin scripts for container invocations (apptainer exec, singularity run,
docker run) and extracts the interface: what executables are called, what files
are expected, what bind mounts are needed, what environment is set.

The goal: catalog the CONTRACT (inputs/outputs/commands), not the internals.
The container is a black box. We document its labels.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)

CONTAINERS_FILE = "containers.yaml"


# ═══════════════════════════════════════════════════════════════════════
# Container invocation detection
# ═══════════════════════════════════════════════════════════════════════

# Patterns that indicate container execution
_CONTAINER_PATTERNS = [
    # apptainer/singularity exec|run|shell ... image
    # Image is the last argument before the command, typically quoted or a .sif path
    re.compile(
        r'(?:apptainer|singularity)\s+(?:exec|run|shell)\s+'
        r'(?P<flags>(?:--\S+\s+\S+\s+)*?)'  # non-greedy flags
        r'["\']?(?P<image>\$\{?\w+\}?|/\S+\.sif\b|osdf://\S+)["\']?',
        re.IGNORECASE,
    ),
    # docker run ... image
    re.compile(
        r'docker\s+run\s+(?P<flags>.*?)\s+(?P<image>\S+:\S+|\S+/\S+)',
        re.IGNORECASE,
    ),
    # +SingularityImage (HTCondor)
    re.compile(
        r'\+SingularityImage\s*=\s*["\']?(?P<image>\S+?)["\']?\s*$',
    ),
    # CONTAINER_IMAGE= assignment (captures the actual path)
    re.compile(
        r'(?:CONTAINER_IMAGE|CONTAINER_SIF|SIF_PATH)\s*=\s*["\']?(?P<image>/\S+\.sif|osdf://\S+)["\']?',
    ),
]

# Patterns for executables called inside container
_EXEC_PATTERNS = [
    # Direct path: /opt/orca/orca, /usr/bin/python3
    re.compile(r'(/opt/\S+|/usr/(?:local/)?bin/\S+)'),
    # Known computational tools
    re.compile(r'\b(orca|gaussian|g16|g09|xtb|crest|multiwfn|vasp|lammps|gromacs|namd)\b', re.IGNORECASE),
]

# Patterns for bind mounts
_BIND_PATTERNS = [
    re.compile(r'--bind\s+(\S+)'),
    re.compile(r'-B\s+(\S+)'),
    re.compile(r'-v\s+(\S+)'),  # docker
    re.compile(r'--volume\s+(\S+)'),
]

# Patterns for environment variables set for containers
_ENV_PATTERNS = [
    re.compile(r'--env\s+(\S+)'),
    re.compile(r'-e\s+(\S+)'),
    re.compile(r'export\s+(OMPI_\w+|OMP_\w+|CUDA_\w+|LD_\w+|PATH)=(\S+)'),
]


def detect_container_usage(plugin_dir: Path) -> List[Dict[str, Any]]:
    """
    Scan all scripts in a plugin for container invocations.

    Returns list of detected container usages, each with:
      - source_file: which script calls the container
      - line_num: where
      - runtime: apptainer | singularity | docker | htcondor_singularity
      - image: container image path/variable
      - flags: bind mounts, env vars, etc.
      - executables_called: what runs inside the container
      - file_inputs: files read by the container
      - file_outputs: files produced by the container
    """
    plugin_dir = Path(plugin_dir)
    detections = []

    script_exts = (".sh", ".bash", ".submit", ".py")
    try:
        from .ignore import load_ignore_patterns, should_ignore
        patterns = load_ignore_patterns(plugin_dir)
    except ImportError:
        patterns = []

    for f in sorted(plugin_dir.rglob("*")):
        if not f.is_file() or f.suffix not in script_exts:
            continue
        if ".bak" in str(f) or "__pycache__" in str(f):
            continue
        if patterns and should_ignore(f, plugin_dir, patterns):
            continue

        try:
            content = f.read_text(errors="ignore")
        except Exception:
            continue

        rel_path = str(f.relative_to(plugin_dir))
        lines = content.splitlines()

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for pattern in _CONTAINER_PATTERNS:
                match = pattern.search(line)
                if match:
                    detection = _analyze_container_invocation(
                        rel_path, line_num, line, match, content, lines
                    )
                    if detection:
                        detections.append(detection)
                    break  # one detection per line

    # Smart deduplication: merge detections that reference the same container
    merged = []
    by_var: Dict[str, int] = {}    # variable name → index in merged
    by_path: Dict[str, int] = {}   # .sif path → index in merged

    for d in detections:
        image = d.get("image", "").strip("\"'")
        line = d.get("line", "")

        # Detect if this is a variable ASSIGNMENT (CONTAINER_IMAGE=/path/to.sif)
        assign_match = re.match(r'(\w+)\s*=\s*["\']?(.+\.sif)', line)
        if assign_match:
            var_name = assign_match.group(1)
            path = assign_match.group(2).strip("\"'")
            by_var[var_name] = len(merged)
            by_path[path] = len(merged)
            merged.append(d)
            continue

        # If it's a variable reference ($CONTAINER_IMAGE)
        if image.startswith("$"):
            var_name = image.strip("${}")
            if var_name in by_var:
                # Merge into existing entry
                idx = by_var[var_name]
                if d.get("runtime", "unknown") != "unknown":
                    merged[idx]["runtime"] = d["runtime"]
                # Merge line as invocation
                if "exec" in line or "run" in line:
                    merged[idx]["invocation_line"] = line
                merged[idx]["bind_mounts"] = sorted(
                    set(merged[idx].get("bind_mounts", []) + d.get("bind_mounts", []))
                )
                merged[idx]["executables"] = sorted(
                    set(merged[idx].get("executables", []) + d.get("executables", []))
                )
                merged[idx]["environment"].update(d.get("environment", {}))
                continue
            else:
                by_var[var_name] = len(merged)
                merged.append(d)

        elif image.endswith(".sif") or "osdf://" in image:
            if image in by_path:
                # Merge
                idx = by_path[image]
                if d.get("runtime", "unknown") != "unknown":
                    merged[idx]["runtime"] = d["runtime"]
                merged[idx]["executables"] = sorted(
                    set(merged[idx].get("executables", []) + d.get("executables", []))
                )
                continue
            by_path[image] = len(merged)
            merged.append(d)
        else:
            merged.append(d)

    return merged


def _analyze_container_invocation(
    source_file: str,
    line_num: int,
    line: str,
    match: re.Match,
    full_content: str,
    all_lines: List[str],
) -> Optional[Dict[str, Any]]:
    """Analyze a single container invocation and extract the interface."""

    detection: Dict[str, Any] = {
        "source_file": source_file,
        "line_num": line_num,
        "line": line.strip(),
    }

    # Determine runtime
    line_lower = line.lower()
    if "apptainer" in line_lower:
        detection["runtime"] = "apptainer"
    elif "singularity" in line_lower:
        detection["runtime"] = "singularity"
    elif "docker" in line_lower:
        detection["runtime"] = "docker"
    elif "SingularityImage" in line:
        detection["runtime"] = "htcondor_singularity"
    else:
        detection["runtime"] = "unknown"

    # Extract image
    groups = match.groupdict()
    detection["image"] = groups.get("image", "")

    # Extract bind mounts from surrounding context
    bind_mounts = set()
    # Search nearby lines (±10) for bind/volume flags
    context_start = max(0, line_num - 10)
    context_end = min(len(all_lines), line_num + 10)
    context = "\n".join(all_lines[context_start:context_end])

    for bp in _BIND_PATTERNS:
        for bm in bp.finditer(context):
            bind_mounts.add(bm.group(1))
    detection["bind_mounts"] = sorted(bind_mounts)

    # Extract environment variables
    env_vars = {}
    for ep in _ENV_PATTERNS:
        for em in ep.finditer(full_content):
            if em.lastindex and em.lastindex >= 2:
                env_vars[em.group(1)] = em.group(2)
            elif em.lastindex and em.lastindex >= 1:
                val = em.group(1)
                if "=" in val:
                    k, v = val.split("=", 1)
                    env_vars[k] = v
                else:
                    env_vars[val] = ""
    detection["environment"] = env_vars

    # Extract executables called inside container
    executables = set()
    # Look at what's called after the container command
    # Also scan the full file for executable paths
    for ep in _EXEC_PATTERNS:
        for em in ep.finditer(full_content):
            exe = em.group(1) if em.group(1).startswith("/") else em.group(0)
            executables.add(exe)
    detection["executables"] = sorted(executables)

    # Extract file I/O patterns from the script
    file_inputs, file_outputs = _detect_file_io(full_content)
    detection["file_inputs"] = file_inputs
    detection["file_outputs"] = file_outputs

    return detection


def _detect_file_io(content: str) -> tuple:
    """Detect file input/output patterns from script content."""
    inputs = set()
    outputs = set()

    # Input file patterns
    input_patterns = [
        re.compile(r'(?:cat|read|source|unzip|tar\s+-x)\s+["\']?(\S+\.\w+)["\']?'),
        re.compile(r'\*xyzfile\s+\S+\s+\S+\s+(\S+\.xyz)'),  # ORCA
        re.compile(r'(?:input|inp|geom)\s*=\s*["\']?(\S+\.\w+)["\']?'),
    ]

    # Output file patterns
    output_patterns = [
        re.compile(r'>\s*["\']?(\S+\.\w+)["\']?'),  # redirect
        re.compile(r'tar\s+-[czf]+\s+["\']?(\S+\.tar\.gz)["\']?'),
        re.compile(r'zip\s+.*?(\S+\.zip)'),
        re.compile(r'(?:results|output|status)\.\w+'),
    ]

    for pat in input_patterns:
        for m in pat.finditer(content):
            name = m.group(1) if m.lastindex else m.group(0)
            name = name.strip("\"'${}()")
            if name and not name.startswith("/dev/"):
                inputs.add(name)

    for pat in output_patterns:
        for m in pat.finditer(content):
            name = m.group(1) if m.lastindex else m.group(0)
            name = name.strip("\"'${}()")
            if name and not name.startswith("/dev/"):
                outputs.add(name)

    # Common output patterns in computational chemistry
    for ext in (".out", ".log", ".molden", ".gbw", ".densities", ".wbo"):
        if ext in content:
            outputs.add(f"*{ext}")

    return sorted(inputs), sorted(outputs)


# ═══════════════════════════════════════════════════════════════════════
# Generate containers.yaml
# ═══════════════════════════════════════════════════════════════════════

def generate_containers_yaml(
    plugin_dir: Path,
    detections: List[Dict[str, Any]],
) -> Path:
    """
    Generate a containers.yaml documenting all container interfaces.
    """
    plugin_dir = Path(plugin_dir)

    containers = {}
    for i, d in enumerate(detections):
        # Name the container by image basename or index
        image = d.get("image", "")
        if image:
            name = Path(image.replace("$", "").replace("{", "").replace("}", ""))
            name = name.stem.replace(".", "_")
            if not name or name.startswith("_"):
                name = f"container_{i}"
        else:
            name = f"container_{i}"

        entry: Dict[str, Any] = {
            "image": image,
            "runtime": d.get("runtime", "unknown"),
            "detected_in": d.get("source_file", "?"),
        }

        if d.get("executables"):
            entry["provides"] = []
            for exe in d["executables"]:
                entry["provides"].append({
                    "path": exe,
                    "name": Path(exe).name,
                })

        if d.get("bind_mounts"):
            entry["bind_mounts"] = d["bind_mounts"]

        if d.get("environment"):
            entry["environment"] = d["environment"]

        if d.get("file_inputs"):
            entry["file_inputs"] = d["file_inputs"]

        if d.get("file_outputs"):
            entry["file_outputs"] = d["file_outputs"]

        containers[name] = entry

    result = {"containers": containers}

    yaml_path = plugin_dir / CONTAINERS_FILE
    yaml_path.write_text(
        yaml.dump(result, default_flow_style=False, sort_keys=False, width=120),
        encoding="utf-8",
    )

    return yaml_path


# ═══════════════════════════════════════════════════════════════════════
# Format for LLM prompts
# ═══════════════════════════════════════════════════════════════════════

def format_containers_for_prompt(detections: List[Dict[str, Any]]) -> str:
    """Format container detections as LLM prompt context."""
    if not detections:
        return ""

    parts = [
        "=== CONTAINER INTERFACES (auto-detected from scripts) ===",
        "These containers are used by this workflow. The glue must invoke them correctly.",
        "",
    ]

    for d in detections:
        image = d.get("image", "?")
        runtime = d.get("runtime", "?")
        source = d.get("source_file", "?")

        parts.append(f"── Container: {image} ──")
        parts.append(f"Runtime: {runtime}")
        parts.append(f"Detected in: {source} (line {d.get('line_num', '?')})")
        parts.append(f"Invocation: {d.get('line', '')}")

        if d.get("executables"):
            parts.append(f"Executables inside: {', '.join(d['executables'])}")

        if d.get("bind_mounts"):
            parts.append(f"Bind mounts: {', '.join(d['bind_mounts'])}")

        if d.get("environment"):
            parts.append("Environment:")
            for k, v in d["environment"].items():
                parts.append(f"  {k}={v}")

        if d.get("file_inputs"):
            parts.append(f"Expects files: {', '.join(d['file_inputs'])}")

        if d.get("file_outputs"):
            parts.append(f"Produces files: {', '.join(d['file_outputs'])}")

        parts.append(f"── END Container ──\n")

    parts.append("=== END CONTAINER INTERFACES ===")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Load existing containers.yaml
# ═══════════════════════════════════════════════════════════════════════

def load_containers_yaml(plugin_dir: Path) -> Dict[str, Any]:
    """Load containers.yaml if it exists."""
    yaml_path = Path(plugin_dir) / CONTAINERS_FILE
    if yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"containers": {}}
