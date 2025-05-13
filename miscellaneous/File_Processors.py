#!/usr/bin/env python3
"""
Recursive file processor
========================

Scan **ROOT_DIR** (and its sub‑folders) for files, route each file to a
handler based on its extension, copy it to type‑specific collection
folders in the user’s home directory (``~/Raw-XYZ`` etc.), and invoke
placeholder processing functions (e.g. ``Process_xyz``).

Edit *ROOT_DIR* and extend **DESTDIRS** / **HANDLERS** to support other
file types as needed.

Requirements
------------
* Python ≥ 3.8
* Standard library only (``pathlib`` & ``shutil``)
"""
from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path
from typing import Callable, Dict
from separate_xyz import split_xyz_files
from docx_to_txt import DOCX_TO_TXT

# --------------------------------------------------
# Configuration
# --------------------------------------------------

# Shell‑style patterns for directories that should be skipped
IGNORE_PATTERNS = ["*Raw*", "__MACOSX"]

# --------------------------------------------------
# Helper utilities
# --------------------------------------------------

def is_in_ignored_dir(p: Path) -> bool:
    """Return *True* if *p* resides in (or *is*) a directory matching IGNORE_PATTERNS."""
    return any(
        fnmatch.fnmatch(part, pattern)
        for part in p.parts
        for pattern in IGNORE_PATTERNS
    )

def copy_unique(src: Path, dest_dir: Path) -> Path:
    """Copy *src* to *dest_dir*, renaming to avoid collisions."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    counter = 1
    while dst.exists():
        dst = dest_dir / f"{src.stem}_{counter}{src.suffix}"
        counter += 1
    shutil.copy2(src, dst)
    return dst

# --------------------------------------------------
# Placeholder processing functions (extend/replace as needed)
# --------------------------------------------------

def process_xyz(file_path: Path, dest_dir: Path) -> None:  # noqa: N802
    new_path = copy_unique(file_path, dest_dir)
    try:
        # real implementation lives elsewhere
        split_xyz_files(new_path)  # type: ignore[name-defined]
    except NameError:
        print(f"[SKIP] Process_xyz not implemented for {new_path}")

def process_pdf(file_path: Path, dest_dir: Path) -> None:
    copy_unique(file_path, dest_dir)
    # future: call your own PDF processor here


def process_txt(file_path: Path, dest_dir: Path) -> None:
    copy_unique(file_path, dest_dir)
    # future: call your own TXT processor here

def process_docx(file_path: Path, dest_dir: Path) -> None:
    new_path = copy_unique(file_path, dest_dir)
    try:
        DOCX_TO_TXT(new_path)
    except:
        print(f"CANNOT PROCESS DOCX for {new_path}")
# Register handlers – extend this dict to support more types
HANDLERS: Dict[str, Callable[[Path, Path], None]] = {
    ".xyz":  process_xyz,
    ".pdf":  process_pdf,
    ".txt":  process_txt,
    ".docx": process_docx,
}

# --------------------------------------------------
# Main routine
# --------------------------------------------------
HOME_DIR: Path = Path(".").expanduser().resolve()

for folder in HOME_DIR.rglob("*/"):
    print(folder)
    ROOT_DIR = folder
    directory = "S41467-018-03793-W"
    ROOT_DIR: Path = Path(directory).expanduser().resolve()
    
    # Mapping from file extension → destination directory in $HOME
    DESTDIRS: Dict[str, Path] = {
        ".xyz": ROOT_DIR / "Raw-XYZ",
        ".pdf": ROOT_DIR / "Raw-PDF",
        ".txt": ROOT_DIR / "Raw-TXT",
        ".docx": ROOT_DIR / "Raw-DOCX",
    }
    if not ROOT_DIR.is_dir():
        raise SystemExit(f"ROOT_DIR '{ROOT_DIR}' does not exist or is not a directory.")
    
    for path in ROOT_DIR.rglob("*"):
        if is_in_ignored_dir(path):
                # Skip files *and* directories whose path includes Raw-* patterns
                continue
        if not path.is_file():
            continue
        handler = HANDLERS.get(path.suffix.lower())
        if handler:
            print(f"Processing {path.relative_to(ROOT_DIR)}")
            handler(path, DESTDIRS[path.suffix.lower()])