#!/usr/bin/env python3
"""
Merge every */DOI/<DOI_STRING> directory in a tree into a single destination,
renaming colliding filenames as   name.ext → name_2.ext, name_3.ext, …

Adjust SRC_ROOT, DEST_ROOT, and MOVE Originals as desired,
then   python merge_doi_folders.py
"""

from pathlib import Path
import shutil

# ─── USER SETTINGS ────────────────────────────────────────────────────────────
SRC_ROOT   = Path(".")              # project root to scan
DEST_ROOT  = Path("combined-DOI")   # where consolidated DOI folders go
MOVE_ORIGS = True                  # True → delete originals after copy
# ──────────────────────────────────────────────────────────────────────────────


def next_available(dest: Path) -> Path:
    """Return a Path that does not yet exist (adds _2, _3 … if needed)."""
    if not dest.exists():
        return dest
    stem, suf, n = dest.stem, dest.suffix, 2
    while True:
        candidate = dest.with_name(f"{stem}_{n}{suf}")
        if not candidate.exists():
            return candidate
        n += 1


def copy_file(src_file: Path, dest_dir: Path) -> None:
    """Copy src_file into dest_dir, auto-renaming if a collision occurs."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = next_available(dest_dir / src_file.name)
    shutil.copy2(src_file, target)


def process_doi_folder(src_dir: Path) -> None:
    """Copy everything inside one DOI folder into DEST_ROOT/<doi>/…"""
    doi = src_dir.name                    # e.g. "DC10001"
    dest_dir = DEST_ROOT / doi
    for item in src_dir.rglob("*"):
        if item.is_file():
            copy_file(item, dest_dir)


def main() -> None:
    src_root = SRC_ROOT.resolve()
    dst_root = DEST_ROOT.resolve()
    print(f"Scanning {src_root}…")

    doi_dirs = [p for p in src_root.glob("*/DOI/*") if p.is_dir()]
    if not doi_dirs:
        print("No DOI folders found.")
        return

    for d in doi_dirs:
        process_doi_folder(d)

    if MOVE_ORIGS:
        for d in doi_dirs:
            shutil.rmtree(d)
        print("Original DOI folders removed.")

    print(f"✅ All DOI folders consolidated under {dst_root}")


if __name__ == "__main__":
    main()
