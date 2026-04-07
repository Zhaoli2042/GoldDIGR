"""
pipeline.plugins.library – Concept-based snippet library.

Organizes tested code blocks by CONCEPT (what it does) with VARIANTS
(how it does it on different schedulers/infrastructure).

Structure:
  plugins/_library/
    index.yaml              ← master index of all concepts + variants
    submission/             ← CONCEPT: job submission
      _concept.yaml         ← interface, invariants, variant list
      htcondor_osg.sh       ← VARIANT: HTCondor on OSPool
      htcondor_crc.sh       ← VARIANT: HTCondor on CRC (shared FS)
      sge.sh                ← VARIANT: SGE
    health_monitor/
      _concept.yaml
      htcondor.sh
    orca_singlepoint/
      _concept.yaml
      input_template.inp
      driver_with_watchdog.sh
    ...

Concepts don't duplicate. Variants are organized by what makes
them different (scheduler, infrastructure). Invariants encode
hard-won lessons that apply to ALL variants.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

LIBRARY_DIR = "_library"
INDEX_FILE = "index.yaml"


# ═══════════════════════════════════════════════════════════════════════
# Library I/O
# ═══════════════════════════════════════════════════════════════════════

def get_library_path(plugins_root: Path) -> Path:
    """Get or create the library directory."""
    lib = plugins_root / LIBRARY_DIR
    lib.mkdir(exist_ok=True)
    return lib


def load_index(plugins_root: Path) -> Dict[str, Any]:
    """Load the master index."""
    idx_path = plugins_root / LIBRARY_DIR / INDEX_FILE
    if idx_path.exists():
        try:
            data = yaml.safe_load(idx_path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"concepts": {}}


def save_index(plugins_root: Path, index: Dict[str, Any]) -> Path:
    """Save the master index."""
    lib = get_library_path(plugins_root)
    idx_path = lib / INDEX_FILE
    idx_path.write_text(
        yaml.dump(index, default_flow_style=False, sort_keys=False, width=120),
        encoding="utf-8",
    )
    return idx_path


def load_concept(plugins_root: Path, concept_name: str) -> Optional[Dict[str, Any]]:
    """Load a concept's _concept.yaml."""
    concept_dir = plugins_root / LIBRARY_DIR / concept_name
    concept_file = concept_dir / "_concept.yaml"
    if concept_file.exists():
        try:
            return yaml.safe_load(concept_file.read_text())
        except Exception:
            pass
    return None


def save_concept(plugins_root: Path, concept_name: str, concept: Dict[str, Any]) -> Path:
    """Save a concept's _concept.yaml."""
    concept_dir = get_library_path(plugins_root) / concept_name
    concept_dir.mkdir(exist_ok=True)
    concept_file = concept_dir / "_concept.yaml"
    concept_file.write_text(
        yaml.dump(concept, default_flow_style=False, sort_keys=False, width=120),
        encoding="utf-8",
    )
    return concept_file


# ═══════════════════════════════════════════════════════════════════════
# Variant management
# ═══════════════════════════════════════════════════════════════════════

def save_variant(
    plugins_root: Path,
    concept_name: str,
    variant_name: str,
    code: str,
    variant_meta: Dict[str, Any],
) -> Path:
    """
    Save a variant file under a concept directory and update the concept + index.

    Args:
        concept_name: e.g., "submission"
        variant_name: e.g., "htcondor_crc"
        code: the actual file content
        variant_meta: scheduler, infrastructure, tested_by, notes, etc.
    """
    lib = get_library_path(plugins_root)
    concept_dir = lib / concept_name
    concept_dir.mkdir(exist_ok=True)

    # Determine extension
    ext = _guess_extension(code, variant_meta)
    filename = f"{variant_name}{ext}"
    filepath = concept_dir / filename

    filepath.write_text(code, encoding="utf-8")
    if ext == ".sh":
        filepath.chmod(filepath.stat().st_mode | 0o755)

    # Update concept's variant list
    concept = load_concept(plugins_root, concept_name) or {
        "name": concept_name,
        "description": "",
        "interface": {},
        "invariants": [],
        "variants": {},
    }

    concept["variants"][variant_name] = {
        "file": filename,
        "lines": code.count("\n"),
        **variant_meta,
    }
    save_concept(plugins_root, concept_name, concept)

    # Update master index
    index = load_index(plugins_root)
    if "concepts" not in index:
        index["concepts"] = {}

    if concept_name not in index["concepts"]:
        index["concepts"][concept_name] = {
            "description": concept.get("description", ""),
            "n_variants": 0,
        }

    index["concepts"][concept_name]["n_variants"] = len(concept["variants"])
    save_index(plugins_root, index)

    return filepath


def _guess_extension(code: str, meta: Dict) -> str:
    """Guess file extension from content and metadata."""
    first_line = code.strip().split("\n")[0] if code.strip() else ""
    if first_line.startswith("#!/bin/bash") or first_line.startswith("#!/usr/bin/env bash"):
        return ".sh"
    if "python" in first_line:
        return ".py"
    tool = meta.get("tool", "")
    if tool in ("orca", "gaussian"):
        return ".inp"
    if tool in ("pytorch", "tensorflow", "python"):
        return ".py"
    if "import " in code[:200]:
        return ".py"
    if "!" in code[:5] and ("end" in code.lower() or "*xyz" in code.lower()):
        return ".inp"
    return ".sh"


# ═══════════════════════════════════════════════════════════════════════
# Search and selection
# ═══════════════════════════════════════════════════════════════════════

def list_concepts(plugins_root: Path) -> List[Dict[str, Any]]:
    """List all concepts with their variant counts."""
    index = load_index(plugins_root)
    results = []
    for name, meta in index.get("concepts", {}).items():
        concept = load_concept(plugins_root, name)
        if concept:
            results.append({
                "name": name,
                "description": concept.get("description", ""),
                "n_variants": len(concept.get("variants", {})),
                "invariants": concept.get("invariants", []),
                "interface": concept.get("interface", {}),
            })
    return results


def find_best_variant(
    plugins_root: Path,
    concept_name: str,
    *,
    scheduler: Optional[str] = None,
    shared_fs: Optional[bool] = None,
    tool: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Find the best-matching variant for a concept given target infrastructure.

    Scoring: exact scheduler match > same FS model > any match > None
    Returns variant metadata + code content, or None.
    """
    concept = load_concept(plugins_root, concept_name)
    if not concept:
        return None

    variants = concept.get("variants", {})
    if not variants:
        return None

    # Score each variant
    scored = []
    for vname, vmeta in variants.items():
        score = 0
        infra = vmeta.get("infrastructure", {})

        # Scheduler match
        v_sched = vmeta.get("scheduler") or infra.get("scheduler", "")
        if scheduler and v_sched == scheduler:
            score += 10
        elif v_sched in ("any", ""):
            score += 3

        # Filesystem match
        v_shared = infra.get("filesystem", "")
        if shared_fs is not None:
            if shared_fs and v_shared in ("shared", "nfs", "afs", "gpfs"):
                score += 5
            elif not shared_fs and v_shared in ("isolated", "htcondor_transfer"):
                score += 5

        # Tool match
        v_tool = vmeta.get("tool", "")
        if tool and v_tool == tool:
            score += 3
        elif v_tool in ("any", ""):
            score += 1

        # Tested is a bonus
        if vmeta.get("tested_by"):
            score += 1

        scored.append((score, vname, vmeta))

    if not scored:
        return None

    # Best match
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_name, best_meta = scored[0]

    if best_score == 0:
        # No meaningful match — still return the first variant as a reference
        pass

    # Load code
    lib = plugins_root / LIBRARY_DIR / concept_name
    filepath = lib / best_meta.get("file", "")
    code = ""
    if filepath.exists():
        code = filepath.read_text(errors="ignore")

    return {
        "variant_name": best_name,
        "concept_name": concept_name,
        "code": code,
        "score": best_score,
        **best_meta,
    }


def find_concepts_for_workflow(
    plugins_root: Path,
    *,
    scheduler: Optional[str] = None,
    shared_fs: Optional[bool] = None,
    tools: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Find all concepts relevant to a workflow and select the best variant for each.

    Returns list of concepts with their best-matching variant selected.
    """
    results = []
    index = load_index(plugins_root)

    for concept_name in index.get("concepts", {}):
        concept = load_concept(plugins_root, concept_name)
        if not concept:
            continue

        # Check if any variant matches the tool
        if tools:
            has_matching_tool = False
            for vmeta in concept.get("variants", {}).values():
                if vmeta.get("tool", "any") in tools or vmeta.get("tool") == "any":
                    has_matching_tool = True
                    break
            # Science concepts need tool match; scheduler concepts don't
            if concept.get("category") == "science" and not has_matching_tool:
                continue

        best = find_best_variant(
            plugins_root, concept_name,
            scheduler=scheduler,
            shared_fs=shared_fs,
            tool=tools[0] if tools else None,
        )

        if best:
            results.append({
                "concept": concept_name,
                "description": concept.get("description", ""),
                "invariants": concept.get("invariants", []),
                "interface": concept.get("interface", {}),
                "best_variant": best,
            })

    return results


# ═══════════════════════════════════════════════════════════════════════
# Prompt formatting
# ═══════════════════════════════════════════════════════════════════════

def format_concepts_for_prompt(
    concepts: List[Dict[str, Any]],
    *,
    include_code: bool = True,
    max_code_chars: int = 5000,
) -> str:
    """
    Format selected concepts + best variants as context for LLM prompts.
    """
    if not concepts:
        return ""

    parts = [
        f"=== SNIPPET LIBRARY ({len(concepts)} concepts available) ===",
        "Each concept below includes a TESTED code variant and INVARIANTS (rules that must be preserved).",
        "PREFER using these tested blocks over generating from scratch.",
        "When adapting a variant: preserve invariants, replace {{PLACEHOLDERS}}, keep structural patterns.",
        "",
    ]

    for item in concepts:
        cname = item["concept"]
        desc = item.get("description", "")
        invariants = item.get("invariants", [])
        iface = item.get("interface", {})
        best = item.get("best_variant", {})

        parts.append(f"── CONCEPT: {cname} ──")
        if desc:
            parts.append(f"Description: {desc}")

        if iface.get("inputs"):
            parts.append(f"Inputs: {', '.join(iface['inputs'])}")
        if iface.get("outputs"):
            parts.append(f"Outputs: {', '.join(iface['outputs'])}")
        if iface.get("variables"):
            parts.append(f"Template variables: {', '.join(iface['variables'])}")

        if invariants:
            parts.append("INVARIANTS (must preserve in any adaptation):")
            for inv in invariants:
                parts.append(f"  • {inv}")

        if best:
            vname = best.get("variant_name", "?")
            sched = best.get("scheduler", "?")
            score = best.get("score", 0)
            tested = ", ".join(best.get("tested_by", []))
            parts.append(f"Best variant: {vname} (scheduler: {sched}, match score: {score})")
            if tested:
                parts.append(f"Tested by: {tested}")
            if best.get("notes"):
                parts.append(f"Notes: {best['notes']}")

            if include_code and best.get("code"):
                code = best["code"]
                if len(code) > max_code_chars:
                    code = code[:max_code_chars] + "\n... (truncated)"
                parts.append(f"\nCode ({best.get('lines', '?')} lines):")
                parts.append(code)

        parts.append(f"── END CONCEPT: {cname} ──\n")

    parts.append("=== END SNIPPET LIBRARY ===")
    return "\n".join(parts)
