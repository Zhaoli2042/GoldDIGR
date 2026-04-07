"""
pipeline.plugins.ignore – .golddigrignore support.

Reads a .golddigrignore file (same syntax as .gitignore) from a plugin
directory and provides a filter function to skip matched paths during scanning.

Supports:
  - Directory patterns: MD_test/
  - Glob patterns: *.gbw, *.out
  - Nested paths: antechamber/
  - Comments: # this is a comment
  - Negation: !important.out (keep this even if *.out is ignored)
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

IGNORE_FILE = ".golddigrignore"

# Always ignored regardless of .golddigrignore
_BUILTIN_IGNORE = {
    "__pycache__",
    ".git",
    ".svn",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
}


def load_ignore_patterns(plugin_dir: Path) -> List[str]:
    """
    Load ignore patterns from .golddigrignore.
    Returns list of patterns (without comments/blanks).
    """
    ignore_path = Path(plugin_dir) / IGNORE_FILE
    patterns = list(_BUILTIN_IGNORE)

    if ignore_path.exists():
        try:
            for line in ignore_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
            logger.debug("Loaded %d patterns from %s", len(patterns), ignore_path)
        except Exception as e:
            logger.debug("Error reading %s: %s", ignore_path, e)

    return patterns


def should_ignore(
    filepath: Path,
    plugin_dir: Path,
    patterns: List[str],
) -> bool:
    """
    Check if a file should be ignored based on .golddigrignore patterns.

    Args:
        filepath: absolute or relative path to check
        plugin_dir: the plugin root (patterns are relative to this)
        patterns: list of ignore patterns

    Returns True if the file should be skipped.
    """
    try:
        rel = str(filepath.relative_to(plugin_dir))
    except ValueError:
        rel = str(filepath)

    rel_parts = Path(rel).parts
    filename = filepath.name

    # Check negation patterns first (lines starting with !)
    negated = False
    for pat in patterns:
        if pat.startswith("!"):
            neg_pat = pat[1:]
            if _matches(rel, rel_parts, filename, neg_pat):
                negated = True
                break

    if negated:
        return False

    # Check ignore patterns
    for pat in patterns:
        if pat.startswith("!"):
            continue
        if _matches(rel, rel_parts, filename, pat):
            return True

    return False


def _matches(rel: str, rel_parts: tuple, filename: str, pattern: str) -> bool:
    """Check if a relative path matches a single pattern."""
    pattern = pattern.rstrip("/")

    # Directory pattern (ends with /): match any path component
    if pattern.endswith("/") or pattern + "/" in rel + "/":
        pass  # handled below

    # Exact filename match: *.gbw matches foo/bar.gbw
    if fnmatch.fnmatch(filename, pattern):
        return True

    # Match against full relative path
    if fnmatch.fnmatch(rel, pattern):
        return True

    # Match against any path component (directory name)
    for part in rel_parts:
        if fnmatch.fnmatch(part, pattern):
            return True

    # Match with wildcard path prefix
    if fnmatch.fnmatch(rel, f"*/{pattern}"):
        return True
    if fnmatch.fnmatch(rel, f"{pattern}/*"):
        return True
    if fnmatch.fnmatch(rel, f"*/{pattern}/*"):
        return True

    return False


def filter_paths(
    paths: List[Path],
    plugin_dir: Path,
    patterns: Optional[List[str]] = None,
) -> List[Path]:
    """
    Filter a list of paths, removing those matching ignore patterns.

    If patterns is None, loads from .golddigrignore automatically.
    """
    if patterns is None:
        patterns = load_ignore_patterns(plugin_dir)

    return [p for p in paths if not should_ignore(p, plugin_dir, patterns)]
