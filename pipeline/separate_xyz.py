"""
separate_xyz.py – Core XYZ coordinate detection, format conversion, and
                  multi-block splitting.

Combines the proven logic from:
  - separate_xyz.py   (is_xyz_line, _smart_split, _is_xyz_float, VALID_SYMBOLS)
  - second_test_sep.py (improved repack_xyz_blocks with energy-line filtering
                        and smart comment/name extraction)

Dependencies: periodictable (pip install periodictable)
"""

from __future__ import annotations
import re
import logging
from pathlib import Path
from typing import List

import periodictable as pt

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════
# Element lookup tables
# ═════════════════════════════════════════════════════════════════════════
VALID_SYMBOLS = {el.symbol for el in pt.elements if el.number > 0}
NUM2SYM = {el.number: el.symbol for el in pt.elements if el.number > 0}

FLOAT_RE = re.compile(r"[-+]?\d*\.\d+")
FORBIDDEN_CHARS = set("=%()!@°")


# ═════════════════════════════════════════════════════════════════════════
# Low-level helpers
# ═════════════════════════════════════════════════════════════════════════
def _smart_split(raw: str) -> List[str]:
    """
    Split by whichever delimiter (comma, semicolon, tab, pipe) yields the
    most tokens. Falls back to whitespace splitting.
    """
    raw = raw.rstrip("\n\r")
    best = raw.split()
    for sep in [",", ";", "\t", "|"]:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            if len(parts) > len(best):
                best = parts
    return best


def _is_xyz_float(tok: str) -> bool:
    """True for float tokens with ≥1 digit after the decimal point."""
    try:
        float(tok)
    except ValueError:
        return False

    # Scientific notation is always accepted
    if "e" in tok.lower():
        return True

    if "." not in tok:
        return False

    # Normalize unicode dashes
    for dash in ["−", "–", "—"]:
        tok = tok.replace(dash, "-")

    _, frac = tok.lstrip("+-").split(".", 1)
    return frac.isdigit() and len(frac) >= 1


# ═════════════════════════════════════════════════════════════════════════
# Core XYZ line detector
# ═════════════════════════════════════════════════════════════════════════
def is_xyz_line(line: str) -> bool:
    """
    Return True if *line* looks like a valid XYZ-coordinate entry.

    Rules (all must pass):
    1. No forbidden symbols (= % ( ) ! @ °).
    2. Exactly three floats appear in the line, each with ≥1 decimal digit.
    3. Those three floats are the last three tokens; nothing follows them.
    4. ≤ 4 alphabetic characters total in the line.
    5. The first token that contains letters starts with a valid element symbol.
    """
    # Normalize en-dash to ASCII minus
    line = line.replace("–", "-")

    # 0. Reject non-ASCII
    if any(ord(ch) > 127 for ch in line):
        return False

    # 1. Forbidden symbols
    if any(sym in line for sym in FORBIDDEN_CHARS):
        return False

    tokens = _smart_split(line)
    if len(tokens) < 4:  # need at least: element + 3 coords
        return False

    # 2–3. Last three tokens must be valid XYZ coordinates
    # Treat bare 0/+0/-0 as tiny floats so they pass the check
    for i in range(-3, 0):
        tok = tokens[i]
        if tok in {"0", "+0", "-0"}:
            sign = tok[0] if tok[0] in "+-" else ""
            tokens[i] = f"{sign}0.0000000001"

    # Re-assemble the corrected line
    line = " ".join(tokens)
    tokens = line.strip().split()

    if not all(_is_xyz_float(t) for t in tokens[-3:]):
        return False

    # Must be exactly those three floats
    float_strings = re.findall(r"[-+]?\d*\.\d+", line)
    if len(float_strings) != 3:
        return False

    # 4. Total letters guard
    if len(re.findall(r"[A-Za-z]", line)) > 4:
        return False

    return True


# ═════════════════════════════════════════════════════════════════════════
# Gaussian format conversion
# ═════════════════════════════════════════════════════════════════════════
def is_gaussian_coord(line: str) -> bool:
    """
    True for lines of the form:
        idx  atomic#  atomType   X   Y   Z
        1    6        0          0.123  -1.234  2.345
    """
    parts = line.strip().split()
    if len(parts) < 6:
        return False
    if not all(p.lstrip("+-").isdigit() for p in parts[:3]):
        return False
    try:
        float(parts[-1]); float(parts[-2]); float(parts[-3])
    except ValueError:
        return False
    return True


def gauss_to_xyz(line: str) -> str:
    """Convert Gaussian-format coordinate line to standard XYZ."""
    p = line.strip().split()
    return "  ".join([p[1], *p[-3:]])


def numeric_xyz_to_symbol_xyz(coord_lines: List[str]) -> List[str]:
    """
    If the first token of every coordinate row is purely numeric
    (atomic number), convert it to the element symbol.
    Otherwise return the list unchanged.
    """
    if any(any(ch.isalpha() for ch in ln.split()[0]) for ln in coord_lines):
        return coord_lines  # already uses symbols

    converted = []
    for ln in coord_lines:
        parts = ln.split()
        try:
            num = int(parts[0])
            parts[0] = NUM2SYM.get(num, parts[0])
        except ValueError:
            pass
        converted.append("  ".join(parts))
    return converted


# ═════════════════════════════════════════════════════════════════════════
# Name extraction & sanitisation (from second_test_sep.py)
# ═════════════════════════════════════════════════════════════════════════
ENERGY_KEYWORDS = {
    "SCF", "DONE", "SUM", "OF", "ELECTRONIC", "AND", "ZERO-POINT",
    "ENERGIES", "ENERGY", "THERMAL", "FREE", "OPT", "SDM", "B3PW91",
    "ESOL", "SOLVATION", "EOPT", "A.U."
}

SPECIAL_CHAR_MAP = {
    "'": "prime",
    "′": "prime",
    "\u2019": "prime",
    "″": "doubleprime",
    "‡": "double_dagger",
    "*": "asterisk",
}


def _replace_special_chars(text: str) -> str:
    for ch, repl in SPECIAL_CHAR_MAP.items():
        text = text.replace(ch, f"_{repl}_")
    return text


def _looks_like_energy_line(cand: str) -> bool:
    """Heuristic: long line containing energy keyword AND a float."""
    return (
        len(cand) > 20
        and any(kw.lower() in cand.lower() for kw in ("electronic", "thermal", "scf"))
        and bool(FLOAT_RE.search(cand))
    )


def extract_clean_name(raw: str) -> str:
    """
    Return a safe file-stem derived from a comment line.

    Keeps useful chemistry tokens, discards energy keywords, floats,
    integers, and tokens containing '='.
    """
    if not raw:
        return "structure"

    raw = _replace_special_chars(raw)

    tokens = [t for t in re.split(r"[\s,]+", raw) if t]
    clean_tokens: List[str] = []
    for tok in tokens:
        up = tok.upper().rstrip(":;")
        if up in ENERGY_KEYWORDS:
            continue
        if "=" in tok:
            continue
        if FLOAT_RE.fullmatch(tok):
            continue
        if re.fullmatch(r"[-+]?\d+", tok):
            continue
        clean_tokens.append(tok)

    if not clean_tokens:
        return ""

    slug = "_".join(clean_tokens)
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:60] or "structure"


# ═════════════════════════════════════════════════════════════════════════
# Main: repack_xyz_blocks (from second_test_sep.py – improved version)
# ═════════════════════════════════════════════════════════════════════════
def repack_xyz_blocks(src: Path, dst: Path | None = None, simple_names: bool = False) -> int:
    """
    Re-scan *src* for XYZ geometry blocks, ignoring any leading atom counts
    that may be wrong, and write a clean multi-block XYZ file plus
    individual .xyz files per block.

    Parameters
    ----------
    src : Path
        The text file (e.g. rm_footer.txt) containing one or many geometries.
    dst : Path | None
        Output master file. Defaults to '<stem>_repacked.xyz' beside src.
    simple_names : bool
        If True, use simple sequential names (01.xyz, 02.xyz, ...).
        If False, derive names from comment lines above each block.

    Returns
    -------
    int
        Number of geometry blocks written.
    """
    lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
    n = len(lines)

    blocks: List[List[str]] = []
    comments: List[str] = []

    i = 0
    while i < n:
        if not is_xyz_line(lines[i]):
            i += 1
            continue

        # Start of a new block
        start = i
        while i < n and is_xyz_line(lines[i]):
            i += 1
        end = i
        coords = lines[start:end]

        # Find best comment line above the block
        comment = ""
        j = start - 1
        while j >= 0 and not comment:
            cand = lines[j].strip()
            if cand and not is_xyz_line(cand) and not cand.isdigit():
                name_trial = extract_clean_name(cand)
                if name_trial:
                    comment = cand
                elif not _looks_like_energy_line(cand):
                    comment = cand
            j -= 1
        if not comment:
            comment = f"Block {len(blocks) + 1}"

        blocks.append(coords)
        comments.append(comment)

    if not blocks:
        return 0

    # Output paths
    if dst is None:
        dst = src.with_name(f"{src.stem}_repacked.xyz")

    split_dir = dst.with_name(f"{src.stem}_blocks")
    split_dir.mkdir(exist_ok=True)

    used_names: set = set()

    with dst.open("w", encoding="utf-8") as fh:
        for idx, (coords_raw, comment) in enumerate(zip(blocks, comments), 1):
            # Convert Gaussian rows on the fly
            coords_clean = [
                gauss_to_xyz(l) if is_gaussian_coord(l) else l.strip()
                for l in coords_raw
            ]
            # Ensure element symbols, not numbers
            coords_clean = numeric_xyz_to_symbol_xyz(coords_clean)
            atom_count = len(coords_clean)

            # Write to master file
            fh.write(f"{atom_count}\n{comment}\n")
            fh.write("\n".join(coords_clean))
            fh.write("\n\n")

            # Determine individual filename
            if simple_names:
                candidate = f"{idx:02d}"
            else:
                slug = extract_clean_name(comment)
                if not slug:
                    slug = f"block_{idx:02d}"

                base_name = f"{idx:02d}_{slug}" if slug else f"{idx:02d}"
                candidate = base_name
                counter = 2
                while candidate.lower() in used_names:
                    candidate = f"{base_name}_{counter}"
                    counter += 1
            used_names.add(candidate.lower())

            indiv_path = split_dir / f"{candidate}.xyz"
            with indiv_path.open("w", encoding="utf-8") as out_fh:
                out_fh.write(f"{atom_count}\n{comment}\n")
                out_fh.write("\n".join(coords_clean))
                out_fh.write("\n")

    logger.info("Repacked %d XYZ blocks from %s → %s", len(blocks), src.name, dst.name)
    return len(blocks)
