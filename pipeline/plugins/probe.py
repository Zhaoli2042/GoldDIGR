"""
pipeline.plugins.probe – Auto-detect target machine infrastructure.

Runs quick, non-invasive checks to determine:
  - Scheduler (SGE, SLURM, HTCondor, PBS, local)
  - Filesystem (shared or isolated)
  - Container runtime (Apptainer, Singularity, Docker, none)
  - MPI availability and scheduler integration
  - GPU availability
  - Network access (internet reachable from login node)
  - Module system (Lmod, Environment Modules)
  - Common paths and environment

No LLM calls. Runs in <10 seconds. Output is a dict/YAML
suitable for injecting into LLM prompts.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


def _run_quiet(cmd: List[str], timeout: int = 5) -> Optional[str]:
    """Run a command quietly, return stdout or None on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def load_saved_probe() -> Optional[Dict[str, Any]]:
    """
    Load probe results saved by the host-side golddigr wrapper.
    The wrapper runs `plugin probe` on the host (where qsub, apptainer, etc.
    are visible) and saves results to data/output/infrastructure_probe.yaml.
    """
    candidates = [
        Path("data/output/infrastructure_probe.yaml"),
    ]
    # Also check from script directory
    script_dir = Path(__file__).resolve().parent.parent.parent
    candidates.append(script_dir / "data" / "output" / "infrastructure_probe.yaml")
    for p in candidates:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text())
                if isinstance(data, dict) and data.get("scheduler"):
                    logger.debug("Loaded saved probe from %s", p)
                    return data
            except Exception:
                pass
    return None


def probe_infrastructure() -> Dict[str, Any]:
    """
    Get infrastructure information. Prefers saved host-side probe results
    (from `./golddigr plugin probe`). Falls back to in-container detection
    which may be limited.
    """
    # Try loading host-side probe first
    saved = load_saved_probe()
    if saved:
        return saved

    # Fall back to in-container detection (limited visibility)
    info: Dict[str, Any] = {
        "_source": "container_fallback",
        "_note": "Run './golddigr plugin probe' on the host for accurate results",
    }

    # ── Basic system info ─────────────────────────────────────────────
    info["hostname"] = platform.node()
    info["os"] = f"{platform.system()} {platform.release()}"
    info["arch"] = platform.machine()

    # ── Scheduler detection ───────────────────────────────────────────
    scheduler = "local"
    scheduler_details = {}

    # SGE / Sun Grid Engine / Univa
    qsub_path = shutil.which("qsub")
    qstat_path = shutil.which("qstat")
    if qsub_path and qstat_path:
        # Distinguish SGE from PBS (both have qsub)
        # SGE has qconf, PBS has pbsnodes
        if shutil.which("qconf"):
            scheduler = "sge"
            version = _run_quiet(["qstat", "-help"])
            if version and "GE" in version:
                scheduler_details["variant"] = "SGE/UGE"
            # Check for parallel environments
            pe_list = _run_quiet(["qconf", "-spl"])
            if pe_list:
                scheduler_details["parallel_envs"] = pe_list.split()
        elif shutil.which("pbsnodes") or shutil.which("qmgr"):
            scheduler = "pbs"
            version = _run_quiet(["qstat", "--version"])
            if version:
                scheduler_details["version"] = version[:100]
        else:
            # Could be either; default to PBS if unsure
            scheduler = "pbs"

    # SLURM
    if shutil.which("sbatch") and shutil.which("squeue"):
        scheduler = "slurm"
        version = _run_quiet(["sbatch", "--version"])
        if version:
            scheduler_details["version"] = version.strip()
        # Check partitions
        partitions = _run_quiet(["sinfo", "-h", "-o", "%P"])
        if partitions:
            scheduler_details["partitions"] = partitions.split()[:10]

    # HTCondor
    if shutil.which("condor_submit") and shutil.which("condor_q"):
        scheduler = "htcondor"
        version = _run_quiet(["condor_version"])
        if version:
            scheduler_details["version"] = version.splitlines()[0] if version else ""

    info["scheduler"] = scheduler
    if scheduler_details:
        info["scheduler_details"] = scheduler_details

    # ── Filesystem ────────────────────────────────────────────────────
    fs_info: Dict[str, Any] = {}
    home = os.environ.get("HOME", "")
    fs_info["home"] = home

    # Check for common shared filesystem indicators
    shared_paths = []
    for path in ["/scratch", "/work", "/projects", "/shared", "/gpfs",
                 "/lustre", "/afs", "/nfs", home]:
        if path and os.path.isdir(path):
            shared_paths.append(path)

    fs_info["accessible_paths"] = shared_paths

    # Determine if filesystem is likely shared
    # AFS, NFS, GPFS, Lustre are shared; /tmp is local
    has_shared = any(p in str(shared_paths) for p in
                     ["/afs", "/nfs", "/gpfs", "/lustre", "/scratch", "/work", "/projects", "/shared"])
    fs_info["shared_filesystem"] = has_shared

    # HTCondor typically does NOT have shared filesystem
    if scheduler == "htcondor":
        fs_info["note"] = "HTCondor often uses file transfer instead of shared filesystem"

    # Check for scratch/tmp
    scratch = os.environ.get("SCRATCH", os.environ.get("TMPDIR", "/tmp"))
    fs_info["scratch"] = scratch

    info["filesystem"] = fs_info

    # ── Container runtime ─────────────────────────────────────────────
    container: Dict[str, Any] = {"available": False}

    for runtime, cmd in [("apptainer", "apptainer"), ("singularity", "singularity"),
                          ("docker", "docker")]:
        path = shutil.which(cmd)
        if path:
            container["available"] = True
            container["runtime"] = runtime
            container["path"] = path
            version = _run_quiet([cmd, "--version"])
            if version:
                container["version"] = version.strip()
            break

    info["container"] = container

    # ── MPI ───────────────────────────────────────────────────────────
    mpi: Dict[str, Any] = {"available": False}

    for cmd in ["mpirun", "mpiexec", "srun"]:
        path = shutil.which(cmd)
        if path:
            mpi["available"] = True
            mpi["command"] = cmd
            mpi["path"] = path

            # Detect variant
            version = _run_quiet([cmd, "--version"])
            if version:
                first_line = version.splitlines()[0] if version else ""
                mpi["version"] = first_line[:100]
                if "Open MPI" in version or "OpenRTE" in version:
                    mpi["variant"] = "openmpi"
                elif "Intel" in version:
                    mpi["variant"] = "intel"
                elif "MPICH" in version or "Hydra" in version:
                    mpi["variant"] = "mpich"
            break

    # Check for scheduler-MPI integration issues
    if mpi["available"] and scheduler == "sge":
        mpi["sge_integration"] = True
        mpi["warning"] = (
            "SGE sets PE_HOSTFILE for MPI jobs. If running MPI inside a container, "
            "the container cannot read the host PE_HOSTFILE. Fix: "
            "export OMPI_MCA_ras=^gridengine (for OpenMPI) before mpirun."
        )
        if os.environ.get("PE_HOSTFILE") or os.path.isdir("/opt/sge"):
            mpi["pe_hostfile_active"] = True

    info["mpi"] = mpi

    # ── GPU ───────────────────────────────────────────────────────────
    gpu: Dict[str, Any] = {"available": False}

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        gpu["available"] = True
        gpu["vendor"] = "nvidia"
        gpu_info = _run_quiet(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
        if gpu_info:
            gpus = [line.strip() for line in gpu_info.splitlines() if line.strip()]
            gpu["devices"] = gpus[:4]
            gpu["count"] = len(gpus)

    # AMD ROCm
    if not gpu["available"] and shutil.which("rocm-smi"):
        gpu["available"] = True
        gpu["vendor"] = "amd"

    info["gpu"] = gpu

    # ── Network ───────────────────────────────────────────────────────
    network: Dict[str, Any] = {}
    try:
        import requests as req
        resp = req.head("https://google.com", timeout=3)
        network["internet"] = True
    except Exception:
        network["internet"] = False

    # Check OSDF access (used by OSPool)
    osdf_accessible = os.path.isdir("/ospool") or os.path.isdir("/cvmfs")
    network["osdf"] = osdf_accessible
    if osdf_accessible:
        network["note"] = "OSDF/CVMFS available — likely an OSPool access point"

    info["network"] = network

    # ── Module system ─────────────────────────────────────────────────
    modules: Dict[str, Any] = {"available": False}

    if shutil.which("module") or os.path.isfile("/etc/profile.d/modules.sh"):
        modules["available"] = True
        # Try to detect Lmod vs Environment Modules
        lmod = os.environ.get("LMOD_DIR") or os.environ.get("LMOD_CMD")
        if lmod:
            modules["type"] = "lmod"
        else:
            modules["type"] = "environment-modules"

    info["modules"] = modules

    # ── Known issue detection (cross-reference patterns) ──────────────
    warnings = []

    if scheduler == "sge" and container.get("available") and mpi.get("available"):
        if mpi.get("variant") == "openmpi":
            warnings.append({
                "pattern": "SGE + container + OpenMPI",
                "issue": "OpenMPI inside container reads SGE PE_HOSTFILE which is inaccessible",
                "fix": "Set OMPI_MCA_ras=^gridengine before mpirun inside the container",
            })

    if scheduler in ("slurm", "sge", "pbs") and not fs_info.get("shared_filesystem"):
        warnings.append({
            "pattern": f"{scheduler} without shared filesystem",
            "issue": "Job scripts may fail if they assume shared paths",
            "fix": "Ensure all input files are staged to local scratch before execution",
        })

    if scheduler == "sge":
        warnings.append({
            "pattern": "SGE job script spool",
            "issue": "SGE copies job scripts to /opt/sge/.../spool/; $(dirname $0) resolves to spool, not submission dir",
            "fix": "Use $SGE_O_WORKDIR instead of $(dirname $0) in all qsub-submitted scripts",
        })

    if scheduler == "htcondor" and not network.get("internet"):
        warnings.append({
            "pattern": "HTCondor without internet",
            "issue": "HTCondor file transfer may fail for OSDF URIs if nodes lack internet",
            "fix": "Pre-stage container images to local storage; use local paths in +SingularityImage",
        })

    if warnings:
        info["warnings"] = warnings

    return info


def format_probe_report(info: Dict[str, Any]) -> str:
    """Format probe results as a human-readable report."""
    lines = ["🔍 Infrastructure Probe Results:", ""]

    # System
    hostname = info.get("hostname", "")
    os_info = info.get("os", "")
    if hostname:
        lines.append(f"   System:      {hostname} ({os_info}, {info.get('arch', '')})")

    # Scheduler
    lines.append(f"   Scheduler:   {info.get('scheduler', '?')}")
    sched_list = info.get("schedulers_available", [])
    if isinstance(sched_list, list) and len(sched_list) > 1:
        lines.append(f"   Available:   {', '.join(sched_list)}")
    sd = info.get("scheduler_details", "")
    if isinstance(sd, str) and sd:
        lines.append(f"                {sd}")
    elif isinstance(sd, dict):
        if sd.get("version"):
            lines.append(f"                {sd['version']}")

    # Filesystem
    fs = info.get("filesystem", {})
    if isinstance(fs, dict):
        shared = fs.get("shared", fs.get("shared_filesystem", False))
        lines.append(f"   Filesystem:  {'Shared' if shared else 'Local/isolated'}"
                     f" (home: {fs.get('home', '?')})")

    # Container
    ct = info.get("container", {})
    if isinstance(ct, dict):
        rt = ct.get("runtime", "none")
        ver = ct.get("version", "")
        if rt and rt != "none":
            lines.append(f"   Container:   {rt} {ver}")
        else:
            lines.append("   Container:   None found")

    # MPI
    mp = info.get("mpi", {})
    if isinstance(mp, dict):
        cmd = mp.get("command", "")
        if cmd:
            lines.append(f"   MPI:         {mp.get('variant', '?')} ({cmd})")
        else:
            lines.append("   MPI:         Not found on host")

    # GPU
    gp = info.get("gpu", {})
    if isinstance(gp, dict):
        if gp.get("nvidia") or gp.get("available"):
            lines.append(f"   GPU:         {gp.get('vendor', 'NVIDIA')}")
        else:
            lines.append("   GPU:         None")

    # Network
    nw = info.get("network", {})
    if isinstance(nw, dict):
        lines.append(f"   Internet:    {'Yes' if nw.get('internet') else 'No'}")

    # Modules
    modules = info.get("modules", "")
    if isinstance(modules, dict) and modules.get("available"):
        lines.append(f"   Modules:     {modules.get('type', 'yes')}")
    elif isinstance(modules, str) and modules and modules != "none":
        lines.append(f"   Modules:     {modules}")

    return "\n".join(lines)


def format_probe_for_prompt(info: Dict[str, Any]) -> str:
    """Format probe results as context for LLM prompts.
    Handles both host-saved YAML format and in-container detected format."""
    parts = [
        "=== TARGET INFRASTRUCTURE (auto-detected) ===",
        f"Scheduler: {info.get('scheduler', 'unknown')}",
    ]

    # Multiple schedulers
    sched_list = info.get("schedulers_available", [])
    if sched_list and isinstance(sched_list, list):
        parts.append(f"All schedulers available: {', '.join(sched_list)}")

    # Scheduler details (string or dict)
    sd = info.get("scheduler_details", "")
    if isinstance(sd, str) and sd:
        parts.append(f"  details: {sd}")
    elif isinstance(sd, dict):
        for k, v in sd.items():
            parts.append(f"  {k}: {v}")

    # Filesystem (dict with 'shared' key from host probe, or 'shared_filesystem' from container)
    fs = info.get("filesystem", {})
    if isinstance(fs, dict):
        shared = fs.get("shared", fs.get("shared_filesystem", False))
        parts.append(f"Shared filesystem: {'yes' if shared else 'no'}")
        parts.append(f"Home directory: {fs.get('home', '?')}")
        parts.append(f"Scratch: {fs.get('scratch', '?')}")
        sp = fs.get("shared_paths", "")
        if sp:
            parts.append(f"Shared paths: {sp}")

    # Container (dict with 'runtime' from host probe, or 'available' from container)
    ct = info.get("container", {})
    if isinstance(ct, dict):
        rt = ct.get("runtime", "none")
        ver = ct.get("version", "")
        parts.append(f"Container runtime: {rt} {ver}".strip())

    # MPI
    mp = info.get("mpi", {})
    if isinstance(mp, dict):
        cmd = mp.get("command", "")
        variant = mp.get("variant", "unknown")
        if cmd:
            parts.append(f"MPI: {variant} ({cmd})")
            ver = mp.get("version", "")
            if ver:
                parts.append(f"  version: {ver}")
            warn = mp.get("warning", "")
            if warn:
                parts.append(f"MPI WARNING: {warn}")
        else:
            parts.append("MPI: not found on host")

    # GPU
    gp = info.get("gpu", {})
    if isinstance(gp, dict):
        if gp.get("nvidia") or gp.get("available") or gp.get("vendor"):
            vendor = gp.get("vendor", "nvidia" if gp.get("nvidia") else "unknown")
            parts.append(f"GPU: yes ({vendor})")
        else:
            parts.append("GPU: no")

    # Network
    nw = info.get("network", {})
    if isinstance(nw, dict):
        parts.append(f"Internet: {'yes' if nw.get('internet') else 'no'}")
        parts.append(f"OSDF/CVMFS: {'yes' if nw.get('osdf') else 'no'}")

    # Modules
    modules = info.get("modules", "")
    if isinstance(modules, dict):
        if modules.get("available"):
            parts.append(f"Module system: {modules.get('type', 'yes')}")
    elif isinstance(modules, str) and modules and modules != "none":
        parts.append(f"Module system: {modules}")

    # Warnings (from container-side detection)
    warnings = info.get("warnings", [])
    if warnings and isinstance(warnings, list):
        parts.append("")
        parts.append("KNOWN ISSUES FOR THIS INFRASTRUCTURE:")
        for w in warnings:
            if isinstance(w, dict):
                parts.append(f"  - [{w.get('pattern', '?')}] {w.get('issue', '?')}")
                parts.append(f"    Fix: {w.get('fix', '?')}")

    # Source note
    if info.get("_source") == "container_fallback":
        parts.append("")
        parts.append("NOTE: This probe ran inside a container with limited visibility.")
        parts.append("Run './golddigr plugin probe' on the host for accurate results.")

    parts.append("=== END INFRASTRUCTURE ===")
    return "\n".join(parts)
