"""
pipeline.plugins.samples – Sample input file management.

Detects, inspects, and stores sample input files for plugins.
Samples show the exact format chain: golddigr output → glue intermediate → driver input.
These are used by init to generate accurate adapters.

Supports: .xyz, .zip, .tar.gz, .csv, .json, .png, .inp, .com
"""
from __future__ import annotations

import logging
import os
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

SAMPLES_DIR = "samples"
SAMPLES_META = "_samples.yaml"

# Max bytes to read for content preview
_MAX_PREVIEW_BYTES = 3000
# Max files to list inside archives
_MAX_ARCHIVE_LIST = 20


def detect_samples(plugin_dir: Path) -> List[Dict[str, Any]]:
    """
    Auto-detect sample files in a plugin directory.
    Looks in samples/, data/, and the root for common input file types.
    """
    samples = []
    plugin_dir = Path(plugin_dir)

    # Check samples/ first
    search_dirs = [
        plugin_dir / "samples",
        plugin_dir / "data",
        plugin_dir / "test_data",
        plugin_dir,  # root (last resort)
    ]

    seen = set()
    sample_exts = (
        ".xyz", ".zip", ".tar.gz", ".tgz", ".csv", ".json",
        ".inp", ".com", ".gjf", ".png", ".jpg", ".tiff",
        ".sdf", ".mol2", ".pdb",
    )

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for f in sorted(search_dir.iterdir()):
            if not f.is_file():
                continue
            # Check extension (handle .tar.gz specially)
            name = f.name
            if name in seen:
                continue

            is_sample = False
            if name.endswith(".tar.gz") or name.endswith(".tgz"):
                is_sample = True
            elif f.suffix in sample_exts:
                is_sample = True

            if is_sample and f.stat().st_size < 50_000_000:  # skip huge files
                seen.add(name)
                samples.append({
                    "path": str(f),
                    "name": name,
                    "relative": str(f.relative_to(plugin_dir)),
                    "size": f.stat().st_size,
                    "type": _classify_file(f),
                })

    return samples


def _classify_file(filepath: Path) -> str:
    """Classify a sample file by type."""
    name = filepath.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "tarball"
    ext = filepath.suffix.lower()
    return {
        ".xyz": "xyz_geometry",
        ".zip": "zip_archive",
        ".csv": "csv_data",
        ".json": "json_data",
        ".inp": "orca_input",
        ".com": "gaussian_input",
        ".gjf": "gaussian_input",
        ".png": "image",
        ".jpg": "image",
        ".tiff": "image",
        ".sdf": "molecular_structure",
        ".mol2": "molecular_structure",
        ".pdb": "protein_structure",
    }.get(ext, "unknown")


def inspect_sample(filepath: Path) -> Dict[str, Any]:
    """
    Inspect a sample file and return a structured description.
    Reads content previews, lists archive contents, counts atoms, etc.
    """
    filepath = Path(filepath)
    info: Dict[str, Any] = {
        "name": filepath.name,
        "size": filepath.stat().st_size,
        "type": _classify_file(filepath),
    }

    ftype = info["type"]

    if ftype == "xyz_geometry":
        info.update(_inspect_xyz(filepath))
    elif ftype == "zip_archive":
        info.update(_inspect_zip(filepath))
    elif ftype == "tarball":
        info.update(_inspect_tarball(filepath))
    elif ftype in ("csv_data", "json_data", "orca_input", "gaussian_input"):
        info["preview"] = _read_preview(filepath)
    elif ftype == "image":
        info["format"] = filepath.suffix.lstrip(".")

    return info


def _read_preview(filepath: Path, max_bytes: int = _MAX_PREVIEW_BYTES) -> str:
    """Read first N bytes of a text file."""
    try:
        return filepath.read_text(errors="ignore")[:max_bytes]
    except Exception:
        return ""


def _inspect_xyz(filepath: Path) -> Dict[str, Any]:
    """Inspect an XYZ geometry file."""
    result: Dict[str, Any] = {}
    try:
        lines = filepath.read_text(errors="ignore").splitlines()
        if len(lines) >= 3:
            result["n_atoms"] = int(lines[0].strip())
            result["comment"] = lines[1].strip()

            # Count unique elements
            elements = set()
            for line in lines[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    elements.add(parts[0])
            result["elements"] = sorted(elements)

            # First few + last few atom lines
            atom_lines = lines[2:2 + result["n_atoms"]]
            if len(atom_lines) > 6:
                preview = atom_lines[:3] + ["..."] + atom_lines[-2:]
            else:
                preview = atom_lines
            result["preview"] = "\n".join([lines[0], lines[1]] + preview)
    except Exception as e:
        result["error"] = str(e)
    return result


def _inspect_zip(filepath: Path) -> Dict[str, Any]:
    """Inspect a zip archive."""
    result: Dict[str, Any] = {}
    try:
        with zipfile.ZipFile(filepath) as zf:
            names = zf.namelist()
            result["n_files"] = len(names)
            result["contents"] = names[:_MAX_ARCHIVE_LIST]

            # Read small text files for preview
            previews = {}
            for name in names[:5]:
                zinfo = zf.getinfo(name)
                if zinfo.file_size < _MAX_PREVIEW_BYTES and not name.endswith((".png", ".jpg")):
                    try:
                        previews[name] = zf.read(name).decode("utf-8", errors="ignore")[:1000]
                    except Exception:
                        pass
            result["file_previews"] = previews

            # Parse naming convention from filename
            stem = filepath.stem
            parts = stem.split("_")
            if len(parts) >= 3:
                result["filename_convention"] = {
                    "parts": parts,
                    "possible_index": parts[0],
                    "possible_charge": parts[-2] if len(parts) >= 3 else "?",
                    "possible_mult": parts[-1] if len(parts) >= 2 else "?",
                }
    except Exception as e:
        result["error"] = str(e)
    return result


def _inspect_tarball(filepath: Path) -> Dict[str, Any]:
    """Inspect a tar.gz archive."""
    result: Dict[str, Any] = {}
    try:
        with tarfile.open(filepath, "r:gz") as tf:
            members = tf.getmembers()
            result["n_files"] = len(members)

            # List structure
            names = [m.name for m in members if m.isfile()][:_MAX_ARCHIVE_LIST]
            dirs = sorted(set(os.path.dirname(n) for n in names if "/" in n))
            result["contents"] = names
            result["directories"] = dirs[:10]

            # Check nested structure
            if dirs:
                result["nesting_depth"] = max(n.count("/") for n in names) if names else 0

            # Read a small file for preview
            for m in members:
                if m.isfile() and m.size < _MAX_PREVIEW_BYTES:
                    name = m.name
                    if name.endswith((".xyz", ".inp", ".txt", ".json", ".csv")):
                        try:
                            f = tf.extractfile(m)
                            if f:
                                result["sample_file"] = {
                                    "name": name,
                                    "content": f.read().decode("utf-8", errors="ignore")[:1000],
                                }
                                break
                        except Exception:
                            pass
    except Exception as e:
        result["error"] = str(e)
    return result


def format_samples_for_prompt(samples: List[Dict[str, Any]]) -> str:
    """Format inspected samples as context for LLM prompts."""
    if not samples:
        return ""

    parts = [
        "=== SAMPLE INPUT FILES ===",
        "These are ACTUAL files from this workflow. Use them to understand",
        "the exact format — do NOT guess.",
        "",
    ]

    for s in samples:
        name = s.get("name", "?")
        ftype = s.get("type", "?")
        size = s.get("size", 0)

        parts.append(f"── Sample: {name} ({ftype}, {size:,} bytes) ──")

        if ftype == "xyz_geometry":
            parts.append(f"Atoms: {s.get('n_atoms', '?')}")
            parts.append(f"Elements: {', '.join(s.get('elements', []))}")
            parts.append(f"Comment line: {s.get('comment', '')}")
            if s.get("preview"):
                parts.append(f"Content:\n{s['preview']}")

        elif ftype == "zip_archive":
            parts.append(f"Files inside: {s.get('n_files', '?')}")
            parts.append(f"Contents: {s.get('contents', [])}")
            conv = s.get("filename_convention", {})
            if conv:
                parts.append(f"Filename parts: {conv.get('parts', [])}")
                parts.append(f"  Possible: index={conv.get('possible_index')}, "
                             f"charge={conv.get('possible_charge')}, "
                             f"mult={conv.get('possible_mult')}")
            for fname, preview in s.get("file_previews", {}).items():
                parts.append(f"  {fname}:\n    {preview[:300]}")

        elif ftype == "tarball":
            parts.append(f"Files: {s.get('n_files', '?')}")
            parts.append(f"Directories: {s.get('directories', [])}")
            parts.append(f"Nesting depth: {s.get('nesting_depth', '?')}")
            parts.append(f"Contents: {s.get('contents', [])}")
            sf = s.get("sample_file", {})
            if sf:
                parts.append(f"Sample inner file ({sf.get('name', '?')}):\n{sf.get('content', '')[:500]}")

        elif s.get("preview"):
            parts.append(f"Preview:\n{s['preview'][:500]}")

        parts.append("")

    parts.append("=== END SAMPLES ===")
    return "\n".join(parts)


def collect_samples_interactive(
    plugin_dir: Path,
    non_interactive: bool = False,
) -> List[Dict[str, Any]]:
    """
    Detect and optionally ask user for sample files.
    Returns list of inspected sample dicts.
    """
    plugin_dir = Path(plugin_dir)
    samples_dir = plugin_dir / SAMPLES_DIR

    # Auto-detect
    detected = detect_samples(plugin_dir)

    if detected:
        print(f"   Found {len(detected)} potential sample file(s):")
        for s in detected:
            print(f"     📄 {s['relative']} ({s['type']}, {s['size']:,} bytes)")
    else:
        print("   No sample files found.")

    # Ask user for additional samples if interactive
    if not non_interactive and not detected:
        print("\n   Sample input files help generate accurate adapters.")
        print("   Place sample files in: plugins/YOUR_PLUGIN/samples/")
        print("   Supported: .xyz, .zip, .tar.gz, .csv, .json, .inp, .com, .png")

        try:
            answer = input("\n   Path to a sample input file (or Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""

        if answer:
            p = Path(answer)
            if p.exists():
                # Copy to samples/
                samples_dir.mkdir(exist_ok=True)
                import shutil
                dest = samples_dir / p.name
                shutil.copy2(p, dest)
                detected.append({
                    "path": str(dest),
                    "name": p.name,
                    "relative": f"samples/{p.name}",
                    "size": dest.stat().st_size,
                    "type": _classify_file(dest),
                })
                print(f"   ✅ Copied to {dest}")
            else:
                print(f"   ⚠ File not found: {answer}")

    # Inspect all detected samples
    inspected = []
    for s in detected:
        filepath = Path(s["path"])
        if filepath.exists():
            info = inspect_sample(filepath)
            info["relative"] = s["relative"]
            inspected.append(info)

    # Save samples metadata
    if inspected:
        meta_path = plugin_dir / SAMPLES_DIR / SAMPLES_META
        if not meta_path.parent.exists():
            # Save metadata alongside the plugin, not in samples/ if it doesn't exist
            meta_path = plugin_dir / SAMPLES_META

        meta = {
            "samples": [
                {
                    "file": s.get("relative", s.get("name", "?")),
                    "type": s.get("type", "?"),
                    "size": s.get("size", 0),
                    "n_atoms": s.get("n_atoms"),
                    "elements": s.get("elements"),
                    "n_files": s.get("n_files"),
                    "contents": s.get("contents"),
                    "directories": s.get("directories"),
                }
                for s in inspected
            ]
        }
        try:
            meta_path.parent.mkdir(exist_ok=True)
            meta_path.write_text(
                yaml.dump(meta, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    return inspected
