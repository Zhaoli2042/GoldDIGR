#!/usr/bin/env python3
"""
batch_split_xyz.py  –  Detect all .xyz files in a folder and split any
                       multi-structure files into separate .xyz files.

Behaviour
---------
┌─ For every  *.xyz*  in <target_dir>
│   • Read the file and count distinct XYZ blocks (using `is_xyz_line`).
│   • If there is more than one block:
│       – Create a sub-folder whose name equals the file stem.
│       – Write each block as  NN_<comment>.xyz  inside that folder.
│   • If there is only one block: leave the file untouched.
└─ Prints a summary of what was split or skipped.

Usage
-----
    # Work in the current directory:
    python batch_split_xyz.py

    # Or give a directory explicitly:
    python batch_split_xyz.py  /path/to/folder
"""

from pathlib import Path
import re
import argparse
from typing import List

# ---------------------------------------------------------------------------
# 1) Low-level detector supplied earlier by you
# ---------------------------------------------------------------------------
def is_xyz_line(line: str) -> bool:
    forbidden = {"=", "%", "(", ")", "!", "@", "°"}
    if any(sym in line for sym in forbidden):
        return False

    floats = re.findall(r'[-+]?\d*\.\d+(?:[eE][-+]?\d+)?', line)
    if len(floats) != 3:
        return False

    letters = re.findall(r'[A-Za-z]', line)
    if len(letters) > 30:
        return False

    integers = re.findall(r'(?<!\.)\b\d+\b(?!\.)', line)
    return bool(letters or integers)


def sanitise(title: str) -> str:
    """Trim a comment line to a safe filename fragment."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", title)[:50] or "structure"


# ---------------------------------------------------------------------------
def split_one_xyz(xyz_path: Path) -> int:
    """
    Split `xyz_path` if it contains multiple structures.
    Returns the number of blocks found (1 = nothing to do).
    """
    lines = xyz_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    blocks: List[List[str]] = []
    i, n = 0, len(lines)

    while i < n:
        if not lines[i].strip():
            i += 1
            continue

        # ---------- block with declared atom count ----------
        if lines[i].strip().isdigit():
            atoms = int(lines[i].strip())
            comment = lines[i + 1] if i + 1 < n else ""
            coords = lines[i + 2 : i + 2 + atoms]
            blocks.append([str(atoms), comment, *coords])
            i += 2 + atoms
            continue

        # ---------- block without atom count ----------
        comment = lines[i]
        coords = []
        i += 1
        while i < n and is_xyz_line(lines[i]):
            coords.append(lines[i])
            i += 1
        if coords:
            blocks.append([str(len(coords)), comment, *coords])

    # Nothing to split?
    if len(blocks) <= 1:
        return 1

    # Folder named after the file stem
    outdir = xyz_path.parent / xyz_path.stem
    outdir.mkdir(exist_ok=True)

    for idx, block in enumerate(blocks, 1):
        outfile = outdir / f"{idx:02d}_{sanitise(block[1])}.xyz"
        outfile.write_text("\n".join(block) + "\n", encoding="utf-8")

    return len(blocks)


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Split every multi-structure XYZ file in a directory."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Target directory (default: current directory)",
    )
    args = parser.parse_args()
    target_dir = Path(args.directory).expanduser().resolve()

    if not target_dir.is_dir():
        raise SystemExit(f"❌  {target_dir} is not a directory")

    xyz_files = sorted(target_dir.glob("*.xyz"))
    if not xyz_files:
        print("No .xyz files found.")
        return

    print(f"Scanning {target_dir} ...")
    for f in xyz_files:
        blocks = split_one_xyz(f)
        if blocks > 1:
            print(f"  ▶  {f.name}: split into {blocks} structures")
        else:
            print(f"  ▫  {f.name}: single structure – skipped")


if __name__ == "__main__":
    main()
