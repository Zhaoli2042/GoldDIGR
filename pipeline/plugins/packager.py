"""
pipeline.plugins.packager – Build ready-to-submit HPC packages.

The packager is intentionally dumb.  It does NOT generate any scheduler-
specific scripts.  All intelligence lives in the plugin's glue/ directory,
which is created by `plugin init` (LLM-generated) or written by hand.

For each completed article the packager:
  1. Copies extracted XYZ files into xyz/
  2. Copies the plugin's scripts/, templates/, glue/ verbatim
  3. Copies cluster.yaml and plugin.yaml
  4. Generates cluster.env (flat key=value from cluster.yaml for bash sourcing)
  5. Tars everything into one self-contained archive
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .registry import load_manifest

logger = logging.getLogger(__name__)


# ── cluster.yaml → cluster.env ──────────────────────────────────────────

def _flatten_yaml(data: dict, prefix: str = "") -> List[str]:
    """Recursively flatten a YAML dict into KEY=VALUE lines for bash."""
    lines = []
    for key, value in data.items():
        flat_key = f"{prefix}{key}".upper().replace("-", "_")
        if isinstance(value, dict):
            lines.extend(_flatten_yaml(value, prefix=f"{flat_key}_"))
        elif isinstance(value, list):
            # Join lists with spaces (e.g. env_setup commands)
            joined = "  ".join(str(v) for v in value)
            lines.append(f'{flat_key}="{joined}"')
            # Also emit individual items as array syntax
            for i, v in enumerate(value):
                lines.append(f'{flat_key}_{i}="{v}"')
            lines.append(f'{flat_key}_COUNT={len(value)}')
        else:
            lines.append(f'{flat_key}="{value}"')
    return lines


def _generate_cluster_env(cluster_yaml: Path) -> str:
    """Convert cluster.yaml to a sourceable bash env file."""
    with open(cluster_yaml) as f:
        data = yaml.safe_load(f) or {}
    lines = [
        "#!/bin/bash",
        "# Auto-generated from cluster.yaml — source this in your glue scripts",
        "# Usage: source cluster.env",
        "",
    ]
    lines.extend(_flatten_yaml(data))
    return "\n".join(lines) + "\n"


# ── Package builder ──────────────────────────────────────────────────────

def package_article(
    article_id: int,
    xyz_dir: Path,
    plugin_dir: Path,
    cluster_yaml: Path,
    output_dir: Path,
) -> Optional[Path]:
    """
    Build a self-contained tarball for one article's XYZ files.

    The tarball contains:
      xyz/              — extracted XYZ files for this article
      scripts/          — user's science code (verbatim copy)
      templates/        — user's templates (verbatim copy)
      glue/             — LLM-generated adapter scripts (verbatim copy)
      plugin.yaml       — workflow manifest
      cluster.yaml      — user's cluster config
      cluster.env       — flat bash-sourceable version of cluster.yaml
      environment.yml   — conda env spec (if present)

    Returns path to tarball, or None if no XYZ files found.
    """
    xyz_files = sorted(xyz_dir.rglob("*.xyz"))
    if not xyz_files:
        logger.info("Article %d: no XYZ files, skipping", article_id)
        return None

    manifest = load_manifest(plugin_dir)
    name = manifest.get("name", "plugin")

    # Create staging directory
    stage_root = output_dir / f"_staging_{article_id}"
    pkg_name = f"article_{article_id}_{name}"
    pkg_dir = stage_root / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # ── Copy XYZ files ────────────────────────────────────────────────
    xyz_pkg = pkg_dir / "xyz"
    xyz_pkg.mkdir()
    for xf in xyz_files:
        shutil.copy2(xf, xyz_pkg / xf.name)

    # ── Copy figures if available ─────────────────────────────────────
    # Look for figures in the standard location
    figures_src = xyz_dir.parent.parent / "figures" / xyz_dir.name
    if figures_src.is_dir():
        shutil.copytree(figures_src, pkg_dir / "figures")
        logger.info("Article %d: included figures from %s", article_id, figures_src)

    # ── Copy plugin directories (scripts, templates, glue) ────────────
    for dirname in ("scripts", "templates", "glue"):
        src = plugin_dir / dirname
        if src.is_dir():
            shutil.copytree(src, pkg_dir / dirname)

    # ── Handle flat layout (scripts in plugin root) ───────────────────
    if not (plugin_dir / "scripts").is_dir():
        _SCRIPT_EXTS = (".py", ".sh", ".bash", ".submit")
        scripts_dst = pkg_dir / "scripts"
        scripts_dst.mkdir(exist_ok=True)
        for f in plugin_dir.iterdir():
            if f.is_file() and f.suffix in _SCRIPT_EXTS:
                shutil.copy2(f, scripts_dst / f.name)

    # ── Make glue scripts executable ──────────────────────────────────
    glue_dir = pkg_dir / "glue"
    if glue_dir.is_dir():
        for f in glue_dir.iterdir():
            if f.is_file() and f.suffix in (".sh", ""):
                f.chmod(f.stat().st_mode | stat.S_IEXEC)

    # ── Copy environment.yml ──────────────────────────────────────────
    env_file = manifest.get("environment", {}).get("file")
    if env_file:
        env_src = plugin_dir / env_file
        if env_src.exists():
            shutil.copy2(env_src, pkg_dir / "environment.yml")

    # ── Copy plugin.yaml + cluster.yaml ───────────────────────────────
    shutil.copy2(plugin_dir / "plugin.yaml", pkg_dir / "plugin.yaml")
    shutil.copy2(cluster_yaml, pkg_dir / "cluster.yaml")

    # ── Generate cluster.env ──────────────────────────────────────────
    env_content = _generate_cluster_env(cluster_yaml)
    (pkg_dir / "cluster.env").write_text(env_content)

    # ── Create tarball ────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    tarball = output_dir / f"{pkg_name}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(pkg_dir, arcname=pkg_name)

    # Cleanup staging
    shutil.rmtree(stage_root)

    logger.info(
        "Article %d: packaged %d XYZ files → %s",
        article_id, len(xyz_files), tarball.name,
    )
    return tarball


def package_all_articles(
    pipeline_db_path: Path,
    xyz_root: Path,
    plugin_dir: Path,
    cluster_yaml: Path,
    output_dir: Path,
) -> List[Path]:
    """Package all completed articles that have XYZ files."""
    tarballs = []

    if not xyz_root.is_dir():
        logger.warning("XYZ root directory not found: %s", xyz_root)
        return tarballs

    for article_dir in sorted(xyz_root.iterdir()):
        if not article_dir.is_dir():
            continue
        try:
            article_id = int(article_dir.name)
        except ValueError:
            continue

        result = package_article(
            article_id, article_dir, plugin_dir, cluster_yaml, output_dir
        )
        if result:
            tarballs.append(result)

    return tarballs
