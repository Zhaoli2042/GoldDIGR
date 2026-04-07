"""
pdf_txt_processing.py – Post-extraction text cleanup for PDF→text output.

Direct port of the original pdf_txt_processing.py / initial-pdf-txt-cleanup.py
logic, packaged as importable functions for the containerized pipeline.

Pipeline:
  1. detect_footer_pattern()  – NLTK-based footer pattern detection
  2. initial_cleanup()        – header/footer removal, blank line cleanup,
                                restrict to XYZ block ±20 lines, TS tagging
  3. continue_cleanup()       – second-pass removal of standalone page numbers
  4. repack_xyz_blocks()      – (from separate_xyz.py) split into .xyz files

Dependencies: nltk, periodictable
"""

from __future__ import annotations
import os
import re
import glob
import logging
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Union, Iterable

logger = logging.getLogger(__name__)

try:
    import nltk
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)
    _HAS_NLTK = True
except ImportError:
    _HAS_NLTK = False
    logger.warning("nltk not installed — footer detection will use fallback")

from .separate_xyz import is_xyz_line, repack_xyz_blocks


# ═════════════════════════════════════════════════════════════════════════
# Footer pattern definitions
# ═════════════════════════════════════════════════════════════════════════
FOOTER_PATTERNS = {
    "Page": r"Page\s*\d+",
    "page": r"page\s*\d+",
    "SI-":  r"SI-\s*\d+",
    "SI":   r"SI\s*\d+",
    "si-":  r"si-\s*\d+",
    "si":   r"si\s*\d+",
    "S-":   r"S-\s*\d+",
    "S":    r"S\s*\d+",
    "s-":   r"s-\s*\d+",
    "s":    r"s\s*\d+",
}


# ═════════════════════════════════════════════════════════════════════════
# Footer pattern detection
# ═════════════════════════════════════════════════════════════════════════
def detect_footer_pattern(text: str) -> Optional[str]:
    """
    Detect the most probable footer pattern in *text* using NLTK tokenization.

    Returns the pattern key (e.g. "S-", "Page") or None.
    Longer keys take precedence when counts tie.
    """
    if _HAS_NLTK:
        sentences = nltk.sent_tokenize(text)
    else:
        # Fallback: split on double newlines or period-space
        sentences = re.split(r"\n\n+|\.\s+", text)

    pattern_occurrences = {}

    for key in FOOTER_PATTERNS:
        combined = r"\b" + re.escape(key) + r"[\s]*\d+\b"
        occurrences = []
        for sentence in sentences:
            if _HAS_NLTK:
                tokens = nltk.regexp_tokenize(sentence, combined)
            else:
                tokens = re.findall(combined, sentence)
            if tokens:
                occurrences.extend(tokens)
        if occurrences:
            pattern_occurrences[key] = occurrences

    if pattern_occurrences:
        most_probable = max(
            pattern_occurrences.items(),
            key=lambda item: (len(item[1]), len(item[0])),
        )
        return most_probable[0]
    return None


# ═════════════════════════════════════════════════════════════════════════
# XYZ indicator heuristics (for files with no strict XYZ lines)
# ═════════════════════════════════════════════════════════════════════════
def contains_xyz_indicators(text: str) -> tuple[bool, list[str]]:
    """
    Heuristic scan for keywords that hint at Cartesian coordinates
    even when no single line passes is_xyz_line().

    Returns (any_found, list_of_indicator_names).
    """
    indicator_patterns = OrderedDict([
        ("coordinate",  r"\bcoordinate\b"),
        ("XYZ",         r"\bxyz\b"),
        ("X Y Z",       r"\bx[ \t]+y[ \t]+z\b"),
        ("geometry",    r"\bgeometry\b"),
        ("geometries",  r"\bgeometries\b"),
    ])
    found = []
    for name, pat in indicator_patterns.items():
        if re.search(pat, text, re.IGNORECASE):
            found.append(name)
    return bool(found), found


# ═════════════════════════════════════════════════════════════════════════
# Header/footer line detection
# ═════════════════════════════════════════════════════════════════════════
def is_header_or_footer(line: str, footer_pattern: str) -> bool:
    """
    Return True if *line* looks like a page header/footer.
    """
    line_stripped = line.strip()
    lower = line_stripped.lower()

    # Common header/footer phrases
    if any(phrase in lower for phrase in [
        "electronic supplementary material",
        "this journal is © the royal society",
        "footnote",
        "supporting information",
    ]):
        return True

    # Basic page numbering patterns
    if re.match(r"^\s*(page|p)\s*\d+$", lower):
        return True
    if re.match(r"^[Ss]\d+$", line_stripped):
        return True

    # Match the detected footer pattern (strict: line = pattern + digits only)
    combined = r"^\s*" + re.escape(footer_pattern) + r"\s*(\d+)\s*$"
    if re.match(combined, lower):
        return True

    return False


# ═════════════════════════════════════════════════════════════════════════
# Blank line removal between XYZ blocks
# ═════════════════════════════════════════════════════════════════════════
def remove_blank_lines_between_xyz(lines: list[str]) -> list[str]:
    """
    Remove contiguous blank lines that are sandwiched between two
    XYZ coordinate lines.
    """
    final_lines = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "":
            start = i
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            end = i
            # Check if blank block is between two XYZ lines
            if (start > 0 and i < len(lines)
                    and is_xyz_line(lines[start - 1])
                    and is_xyz_line(lines[i])):
                continue  # skip the blank block
            else:
                final_lines.extend(lines[start:end])
        else:
            final_lines.append(lines[i])
            i += 1
    return final_lines


# ═════════════════════════════════════════════════════════════════════════
# TS pattern detection
# ═════════════════════════════════════════════════════════════════════════
def contains_ts_pattern(text: str) -> bool:
    """
    Check if text contains indicators of a transition state:
    TS, transition, ‡ (double dagger).
    """
    pattern = r"\bts\b|\btransition\b|\b‡\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


# ═════════════════════════════════════════════════════════════════════════
# Primary cleanup: initial_cleanup()
# ═════════════════════════════════════════════════════════════════════════
def initial_cleanup(
    text: str,
    *,
    footer_matter: bool = False,
) -> dict:
    """
    Full first-pass text cleanup.

    Parameters
    ----------
    text : str
        Raw text content (from StirlingPDF's pdf-to-text output).
    footer_matter : bool
        If True, return early when no footer pattern is detected.

    Returns
    -------
    dict with keys:
        "cleaned_text"  : str or None (the cleaned text, restricted to XYZ region)
        "has_xyz"       : bool (whether XYZ coordinate lines were found)
        "has_ts"        : bool (whether TS indicators were found)
        "footer_pattern": str or None (the detected footer pattern)
        "xyz_indicators": list[str] (indicator names if no strict XYZ found)
    """
    # Detect footer pattern
    detected_pattern = detect_footer_pattern(text)
    if detected_pattern is None:
        logger.debug("No footer pattern detected.")
        if footer_matter:
            return {
                "cleaned_text": None, "has_xyz": False, "has_ts": False,
                "footer_pattern": None, "xyz_indicators": [],
            }
    else:
        logger.debug("Detected footer pattern: '%s'", detected_pattern)

    # Remove header/footer lines
    clean_lines = []
    for line in text.splitlines():
        found = False
        for pat in FOOTER_PATTERNS:
            if is_header_or_footer(line, pat):
                found = True
                break
        if not found:
            clean_lines.append(line)

    # Remove blank lines between XYZ coordinate lines
    final_lines = remove_blank_lines_between_xyz(clean_lines)

    # Restrict to XYZ block with 20-line buffer
    xyz_indices = [i for i, line in enumerate(final_lines) if is_xyz_line(line)]

    if xyz_indices:
        first_index = xyz_indices[0]
        last_index = xyz_indices[-1]
        start_index = max(0, first_index - 20)
        end_index = min(len(final_lines), last_index + 1)
        final_lines = final_lines[start_index:end_index]
        clean_text = "\n".join(final_lines)

        has_ts = contains_ts_pattern(clean_text)

        return {
            "cleaned_text": clean_text,
            "has_xyz": True,
            "has_ts": has_ts,
            "footer_pattern": detected_pattern,
            "xyz_indicators": [],
        }
    else:
        # No XYZ lines found — check for indicators
        full_text = "\n".join(final_lines)
        has_indicators, indicators = contains_xyz_indicators(full_text)

        return {
            "cleaned_text": None,
            "has_xyz": False,
            "has_ts": False,
            "footer_pattern": detected_pattern,
            "xyz_indicators": indicators,
        }


# ═════════════════════════════════════════════════════════════════════════
# Second-pass cleanup: continue_cleanup()
# ═════════════════════════════════════════════════════════════════════════
def continue_cleanup(
    src: Union[str, Path, Iterable[str]],
    min_count: int = 3,
    tolerance: float = 0.40,
) -> List[str]:
    """
    Remove standalone footer page numbers (plus adjacent blank lines).

    The footer lines must mostly form a +1 sequence: at least
    (1 - tolerance) fraction of the gaps are exactly 1.

    Parameters
    ----------
    src : str | Path | Iterable[str]
        The text to clean.
    min_count : int
        Minimum number of numeric candidates before attempting cleanup.
    tolerance : float
        Fraction of allowed out-of-sequence gaps.

    Returns
    -------
    list[str]
        Lines with standalone page numbers removed.
    """
    # Load lines
    if isinstance(src, Path):
        lines = src.read_text(encoding="utf-8").splitlines()
    elif isinstance(src, str):
        lines = src.splitlines()
    else:
        lines = list(src)

    n = len(lines)
    cand_idx: List[int] = []
    cand_nums: List[int] = []

    # Identify numeric lines with a blank or XYZ neighbour
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.isdigit():
            prev_blank = i > 0     and lines[i - 1].strip() == ""
            next_blank = i < n - 1 and lines[i + 1].strip() == ""
            prev_xyz   = i > 0     and is_xyz_line(lines[i - 1])
            next_xyz   = i < n - 1 and is_xyz_line(lines[i + 1])

            if prev_blank or next_blank or prev_xyz or next_xyz:
                cand_idx.append(i)
                cand_nums.append(int(stripped))

    logger.debug("continue_cleanup: cand_nums = %s", cand_nums)

    if len(cand_nums) < min_count:
        return lines  # too few → leave untouched

    # Fuzzy "mostly +1" test
    diffs = [b - a for a, b in zip(cand_nums, cand_nums[1:])]
    if not diffs:
        return lines

    consecutive_ratio = diffs.count(1) / len(diffs)
    if consecutive_ratio < 1 - tolerance:
        return lines  # not footer-like

    # Build set of indexes to drop (number + neighbour blanks)
    drop: set = set(cand_idx)
    for i in cand_idx:
        if i > 0     and lines[i - 1].strip() == "":
            drop.add(i - 1)
        if i < n - 1 and lines[i + 1].strip() == "":
            drop.add(i + 1)

    return [line for j, line in enumerate(lines) if j not in drop]


# ═════════════════════════════════════════════════════════════════════════
# High-level: process a single text file through the full chain
# ═════════════════════════════════════════════════════════════════════════
def process_text_file(
    text: str,
    output_dir: Path,
    stem: str,
    simple_names: bool = False,
) -> dict:
    """
    Run the full cleanup + XYZ extraction chain on a single text string.

    1. initial_cleanup()  → cleaned text restricted to XYZ region
    2. continue_cleanup() → second-pass page number removal
    3. repack_xyz_blocks() → individual .xyz files

    Parameters
    ----------
    text : str
        Raw text from StirlingPDF.
    output_dir : Path
        Directory for output files.
    stem : str
        Base filename stem for outputs.
    simple_names : bool
        If True, use simple sequential XYZ names (01.xyz, 02.xyz).

    Returns
    -------
    dict with results summary.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Initial cleanup
    result = initial_cleanup(text)

    if not result["has_xyz"]:
        logger.info("%s: No XYZ blocks found (indicators: %s)",
                    stem, result["xyz_indicators"])
        return result

    # Write the cleaned text (first pass)
    ts_tag = "" if result["has_ts"] else ".ts_notfound"
    rm_footer_path = output_dir / f"{stem}{ts_tag}.rm_footer.txt"
    rm_footer_path.write_text(result["cleaned_text"], encoding="utf-8")
    logger.info("Wrote cleaned text → %s", rm_footer_path.name)

    # Step 2: Second-pass page number removal
    cleaned_lines = continue_cleanup(result["cleaned_text"])
    rm_footer_path.write_text("\n".join(cleaned_lines), encoding="utf-8")

    # Step 3: Repack into XYZ blocks
    n_blocks = repack_xyz_blocks(rm_footer_path, simple_names=simple_names)
    result["n_blocks"] = n_blocks
    result["rm_footer_path"] = rm_footer_path
    logger.info("%s: Extracted %d XYZ blocks", stem, n_blocks)

    return result


# ═════════════════════════════════════════════════════════════════════════
# Folder-level processing (matches original pdf_txt_cleanup interface)
# ═════════════════════════════════════════════════════════════════════════
def pdf_txt_cleanup(target_dir: str, case: str = "First_time", simple_names: bool = False) -> None:
    """
    Process a folder of text files through the cleanup chain.

    Cases:
      "First_time"      – initial cleanup of all .txt files
      "Process_PDF_XYZ" – repack XYZ blocks from rm_footer files
      "Continue"        – continue cleanup from a file list
      "Fix"             – second-pass page number removal
    """
    target = Path(target_dir)
    if not target.is_dir():
        return

    if case == "First_time":
        txt_files = list(target.glob("*.txt"))
        if any(f.name.endswith(".rm_footer.txt") for f in txt_files):
            return  # already processed

        for txt_file in txt_files:
            if "rm_footer" in txt_file.name:
                continue
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
            process_text_file(text, target, txt_file.stem, simple_names=simple_names)

    elif case == "Process_PDF_XYZ":
        for txt_file in target.glob("*.rm_footer.txt"):
            repack_xyz_blocks(txt_file, simple_names=simple_names)

    elif case == "Fix":
        for txt_file in target.glob("*rm_footer.txt"):
            new_lines = continue_cleanup(txt_file)
            txt_file.write_text("\n".join(new_lines), encoding="utf-8")
