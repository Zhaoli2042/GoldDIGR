"""
link_extractor.py – Find supplementary-information download links in article HTML.

Two-tier approach:
  1. Fast regex/heuristic scan (handles ~80% of publishers)
  2. (Future) LLM fallback for pages where heuristics fail

Refactored from the original extract_links.py with cleaner API.
"""

from __future__ import annotations
import re
import logging
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
from typing import Optional

logger = logging.getLogger(__name__)

# ── Extensions we consider "downloadable SI files" ───────────────────────
AUTO_DOWNLOAD_EXTS = frozenset({
    ".pdf", ".xyz", ".cif", ".txt", ".xlsx", ".mol",
    ".mol2", ".data", ".docx", ".pdb", ".zip", ".csv",
})

# ── Regex for href= / src= attributes ───────────────────────────────────
_ATTR_RE = re.compile(
    r"""(?:href|src)=
        ['"]?
        (?P<url>[^'"\s>]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_links(
    html: str,
    *,
    base_url: Optional[str] = None,
) -> list[str]:
    """
    Return de-duplicated, order-preserving list of URLs from HTML text.
    Relative URLs are resolved against *base_url* if provided.
    """
    seen: set[str] = set()
    links: list[str] = []

    for match in _ATTR_RE.finditer(html):
        url = unescape(match.group("url"))
        if base_url:
            url = urljoin(base_url, url)
        if url not in seen:
            seen.add(url)
            links.append(url)

    return links


def filter_download_links(
    links: list[str],
    *,
    extensions: frozenset[str] = AUTO_DOWNLOAD_EXTS,
    exclude_patterns: Optional[list[str]] = None,
) -> list[str]:
    """
    Keep only links whose path OR query-string filename ends with a known
    downloadable extension.

    Handles both direct file URLs (/files/paper.pdf) and publisher
    download endpoints (/action/downloadSupplement?file=paper.pdf).

    Optionally exclude URLs matching any pattern in *exclude_patterns*.
    """
    from urllib.parse import parse_qs

    exclude_patterns = exclude_patterns or ["RecruitmentKit"]
    result = []
    for url in links:
        parts = urlsplit(url)
        path = parts.path.lower()

        # Check 1: path ends with a known extension (direct file URLs)
        match = any(path.endswith(ext) for ext in extensions)

        # Check 2: query parameter contains a filename with known extension
        # Covers Wiley (/action/downloadSupplement?file=paper.pdf),
        # ACS, and similar publisher download endpoints.
        if not match:
            qs = parse_qs(parts.query)
            for values in qs.values():
                for val in values:
                    val_lower = unquote(val).lower()
                    if any(val_lower.endswith(ext) for ext in extensions):
                        match = True
                        break
                if match:
                    break

        if match and not any(pat in url for pat in exclude_patterns):
            result.append(url)

    return result


def extract_si_links(
    html_path: Path,
    *,
    base_url: Optional[str] = None,
) -> list[str]:
    """
    Convenience: read an HTML file, extract links, filter to downloads.
    Returns only SI-looking download URLs.
    """
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    all_links = extract_links(html, base_url=base_url)
    si_links = filter_download_links(all_links)
    logger.info(
        "Extracted %d SI links from %s (out of %d total)",
        len(si_links), html_path.name, len(all_links),
    )
    return si_links


def deduce_filename(url: str, default: str = "download") -> str:
    """
    Turn a URL into a safe local filename.

    Handles both direct file URLs and publisher download endpoints
    where the real filename is in a query parameter (e.g. ?file=paper.pdf).
    """
    from urllib.parse import parse_qs

    parts = urlsplit(url)
    name = Path(unquote(parts.path)).name

    # If the path doesn't have a useful extension, check query params
    if not name or not any(name.lower().endswith(ext) for ext in AUTO_DOWNLOAD_EXTS):
        qs = parse_qs(parts.query)
        for key in ("file", "filename", "name"):
            if key in qs and qs[key]:
                candidate = unquote(qs[key][0])
                if any(candidate.lower().endswith(ext) for ext in AUTO_DOWNLOAD_EXTS):
                    name = Path(candidate).name
                    break

    name = name or default
    return re.sub(r'[\\/*?<>|"\']', "_", name)


def looks_like_download(url: str) -> bool:
    """Quick heuristic: does the URL path or query filename end with a known extension?"""
    from urllib.parse import parse_qs

    parts = urlsplit(url)
    path = parts.path.lower()
    if any(path.endswith(ext) for ext in AUTO_DOWNLOAD_EXTS):
        return True
    # Check query parameters for filenames
    for values in parse_qs(parts.query).values():
        for val in values:
            if any(unquote(val).lower().endswith(ext) for ext in AUTO_DOWNLOAD_EXTS):
                return True
    return False
