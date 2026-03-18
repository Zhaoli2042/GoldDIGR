"""
file_processors.py – Route downloaded SI files by extension and convert
                     non-PDF formats to text for downstream processing.

Ported from File_Processors.py, docx_to_txt.py, xlsx_to_txt.py, unzip_file.py.
"""

from __future__ import annotations
import fnmatch
import logging
import shutil
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from typing import Callable, Dict, Optional

from .separate_xyz import repack_xyz_blocks

logger = logging.getLogger(__name__)

# Patterns for directories to ignore during recursive scans
IGNORE_PATTERNS = ["*Raw*", "__MACOSX"]


# ═════════════════════════════════════════════════════════════════════════
# Utility functions
# ═════════════════════════════════════════════════════════════════════════
def is_in_ignored_dir(p: Path) -> bool:
    """Return True if *p* resides in a directory matching IGNORE_PATTERNS."""
    return any(
        fnmatch.fnmatch(part, pattern)
        for part in p.parts
        for pattern in IGNORE_PATTERNS
    )


def copy_unique(src: Path, dest_dir: Path, unique: bool = True) -> Path:
    """Copy *src* to *dest_dir*, renaming to avoid collisions."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    counter = 1
    while dst.exists() and unique:
        dst = dest_dir / f"{src.stem}_{counter}{src.suffix}"
        counter += 1
    if not unique:
        dst = dest_dir / f"{src.stem}{src.suffix}"
    shutil.copy2(src, dst)
    return dst


# ═════════════════════════════════════════════════════════════════════════
# Format converters
# ═════════════════════════════════════════════════════════════════════════
def docx_to_txt(source_file: Path) -> Optional[Path]:
    """Convert a .docx file to .txt using docx2txt."""
    try:
        import docx2txt
    except ImportError:
        logger.warning("docx2txt not installed — skipping %s", source_file.name)
        return None

    destination = source_file.with_suffix(".txt")
    try:
        txt = docx2txt.process(str(source_file))
        destination.write_text(txt, encoding="utf-8")
        logger.info("Converted DOCX → %s", destination.name)
        return destination
    except Exception as exc:
        logger.warning("Cannot process DOCX %s: %s", source_file.name, exc)
        return None


def xlsx_to_txt(
    source_file: Path,
    out_dir: Optional[Path] = None,
    sep: str = "\t",
    na_rep: str = "",
) -> list[Path]:
    """Convert an Excel file to one .txt per worksheet."""
    try:
        import pandas as pd
    except ImportError:
        logger.warning("pandas not installed — skipping %s", source_file.name)
        return []

    out_dir = Path(out_dir or source_file.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    try:
        wb = pd.ExcelFile(source_file)
        for sheet in wb.sheet_names:
            df = wb.parse(sheet)
            safe_sheet = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in sheet
            )
            out_file = out_dir / f"{source_file.stem}_{safe_sheet}.txt"
            df.to_csv(out_file, sep=sep, index=False, na_rep=na_rep)
            results.append(out_file)
            logger.info("Converted XLSX sheet '%s' → %s", sheet, out_file.name)
    except Exception as exc:
        logger.warning("Cannot process XLSX %s: %s", source_file.name, exc)

    return results


def unzip_file(source_file: Path) -> list[Path]:
    """Extract a ZIP archive into its parent directory."""
    dest_dir = source_file.parent
    extracted: list[Path] = []

    try:
        with ZipFile(source_file) as zf:
            for member in zf.namelist():
                path = Path(zf.extract(member, path=dest_dir)).resolve()
                extracted.append(path)
        logger.info("Unzipped %s → %d files", source_file.name, len(extracted))
    except BadZipFile:
        logger.warning("Not a valid ZIP: %s", source_file.name)
    except Exception as exc:
        logger.warning("Cannot unzip %s: %s", source_file.name, exc)

    return extracted


# ═════════════════════════════════════════════════════════════════════════
# Per-type handlers
# ═════════════════════════════════════════════════════════════════════════
def process_xyz(file_path: Path, dest_dir: Path) -> Optional[Path]:
    """Copy .xyz file and repack its blocks."""
    new_path = copy_unique(file_path, dest_dir, unique=False)
    try:
        repack_xyz_blocks(new_path)
        return new_path
    except Exception as exc:
        logger.warning("Failed to repack XYZ %s: %s", file_path.name, exc)
        return None


def process_pdf(file_path: Path, dest_dir: Path) -> Path:
    """Copy .pdf file to collection directory."""
    return copy_unique(file_path, dest_dir)


def process_txt(file_path: Path, dest_dir: Path) -> Path:
    """Copy .txt file to collection directory."""
    return copy_unique(file_path, dest_dir)


def process_docx(file_path: Path, dest_dir: Path) -> Optional[Path]:
    """Copy .docx and convert to txt."""
    new_path = copy_unique(file_path, dest_dir)
    return docx_to_txt(new_path)


def process_xlsx(file_path: Path, dest_dir: Path) -> list[Path]:
    """Copy .xlsx and convert to txt."""
    new_path = copy_unique(file_path, dest_dir)
    return xlsx_to_txt(new_path)


def process_zip(file_path: Path, dest_dir: Path) -> list[Path]:
    """Copy .zip and extract."""
    new_path = copy_unique(file_path, dest_dir)
    return unzip_file(new_path)


# Handler registry
HANDLERS: Dict[str, Callable] = {
    ".xyz":  process_xyz,
    ".pdf":  process_pdf,
    ".txt":  process_txt,
    ".docx": process_docx,
    ".xlsx": process_xlsx,
    ".zip":  process_zip,
}


# ═════════════════════════════════════════════════════════════════════════
# Route all files in a download directory
# ═════════════════════════════════════════════════════════════════════════
def route_files(root_dir: Path) -> dict[str, list[Path]]:
    """
    Scan *root_dir* recursively, route each file to a Raw-{TYPE}
    subdirectory, and invoke the appropriate handler.

    Returns a dict mapping extension → list of processed paths.
    """
    dest_dirs = {
        ".xyz":  root_dir / "Raw-XYZ",
        ".pdf":  root_dir / "Raw-PDF",
        ".txt":  root_dir / "Raw-TXT",
        ".docx": root_dir / "Raw-DOCX",
        ".xlsx": root_dir / "Raw-XLSX",
        ".zip":  root_dir / "ZIP",
    }

    results: dict[str, list[Path]] = {}

    # Process ZIPs first (they may contain other file types)
    for path in root_dir.rglob("*.zip"):
        if is_in_ignored_dir(path) or not path.is_file():
            continue
        handler = HANDLERS.get(path.suffix.lower())
        if handler:
            handler(path, dest_dirs[path.suffix.lower()])

    # Then process everything else
    for path in root_dir.rglob("*"):
        if is_in_ignored_dir(path) or not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext == ".zip":
            continue  # already handled
        handler = HANDLERS.get(ext)
        if handler:
            result = handler(path, dest_dirs.get(ext, root_dir / f"Raw-{ext}"))
            results.setdefault(ext, []).append(path)

    return results
