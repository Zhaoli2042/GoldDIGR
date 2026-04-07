"""
metadata.py – Extract article metadata from HTML and produce BibLaTeX entries.

Cleaned-up version of HTML_tag_extract.py with the same META_MAP logic.
"""

from __future__ import annotations
import re
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from unidecode import unidecode

logger = logging.getLogger(__name__)

# ── Tag-name → logical-field mapping ─────────────────────────────────────
META_MAP = {
    "title":     ("citation_title", "dc.title", "og:title"),
    "doi":       ("citation_doi", "dc.identifier", "dc.identifier.doi",
                  "dc.identifier.uri"),
    "author":    ("citation_author", "dc.creator", "author"),
    "abstract":  ("citation_abstract", "dc.description", "description",
                  "og:description"),
    "journal":   ("citation_journal_title", "prism.publicationname",
                  "dc.source"),
    "pub_date":  ("citation_publication_date", "dc.date.issued",
                  "prism.publicationdate", "date", "dc.date",
                  "article:published_time"),
    "volume":    ("citation_volume", "prism.volume", "dc.source.volume"),
    "issue":     ("citation_issue", "prism.number",
                  "prism.issueidentifier", "dc.source.issue"),
    "firstpage": ("citation_firstpage", "prism.startingpage",
                  "dc.identifier.spage"),
    "lastpage":  ("citation_lastpage", "prism.endingpage",
                  "dc.identifier.epage"),
}


def extract_doi(html: str) -> Optional[str]:
    """Extract DOI from HTML meta tags or content.

    Returns the DOI string (e.g., '10.1021/jacs.4c07999') or None.
    The DOI naturally contains a slash — we preserve it as-is.
    """
    # Try meta tags first (most reliable)
    meta = extract_metadata(html)
    doi = meta.get("doi")
    if doi:
        if isinstance(doi, list):
            doi = doi[0]
        # Normalize: strip URL prefix if present
        doi = str(doi).strip()
        for prefix in ("https://doi.org/", "http://doi.org/",
                        "https://dx.doi.org/", "http://dx.doi.org/",
                        "doi:", "DOI:"):
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix):]
                break
        if doi.startswith("10."):
            return doi.strip()

    # Fallback: regex scan of full HTML
    doi_pattern = re.compile(r'10\.\d{4,9}/[^\s"\'<>&]+')
    match = doi_pattern.search(html)
    if match:
        doi = match.group(0).rstrip(".,;)")
        return doi

    return None


def doi_to_path(doi: str) -> str:
    """Convert a DOI to a filesystem-safe relative path.

    Preserves the natural DOI slash (creates two directory levels):
      10.1021/jacs.4c07999 → 10.1021/jacs.4c07999

    Only sanitizes characters that are invalid in filenames.
    """
    # Remove characters unsafe for paths (keep / and .)
    safe = re.sub(r'[\\:*?"<>|]', '_', doi)
    # Strip trailing dots or whitespace from each component
    parts = safe.split("/")
    parts = [p.strip().rstrip(".") for p in parts if p.strip()]
    return "/".join(parts)


def extract_metadata(html: str) -> dict:
    """Parse HTML <meta> tags into a flat metadata dictionary."""
    soup = BeautifulSoup(html, "lxml")
    md: dict[str, list[str]] = defaultdict(list)

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        value = (meta.get("content") or "").strip()
        if not name or not value:
            continue
        for logical, aliases in META_MAP.items():
            if name in aliases:
                md[logical].append(value)
                break

    # De-duplicate within each field
    for k, values in md.items():
        seen: set[str] = set()
        md[k] = [v for v in values if not (v.lower() in seen or seen.add(v.lower()))]

    # Collapse single-item lists
    result = {}
    for k, v in md.items():
        result[k] = v[0] if len(v) == 1 else v

    return result


def metadata_to_biblatex(meta: dict, *, citekey: Optional[str] = None) -> str:
    """Convert a metadata dict into a BibLaTeX @article entry."""

    # Format author list
    authors = meta.get("author", [])
    if isinstance(authors, str):
        authors = [authors]

    def fmt(a: str) -> str:
        if "," in a:
            return a.strip()
        parts = a.strip().split()
        return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else a

    authors_bib = " and ".join(fmt(a) for a in authors) or "???"

    # Year
    year = "????"
    if date_str := meta.get("pub_date"):
        if isinstance(date_str, list):
            date_str = date_str[0]
        m = re.search(r"\d{4}", date_str)
        if m:
            year = m.group()

    # Pages
    fp, lp = meta.get("firstpage"), meta.get("lastpage")
    pages = f"{fp}--{lp}" if fp and lp else (fp or "")

    # Citekey
    if not citekey:
        first_last = unidecode(authors[0].split()[-1]) if authors else "key"
        first_last = re.sub(r"[^A-Za-z0-9]", "", first_last)
        title_word = meta.get("title", "untitled")
        if isinstance(title_word, list):
            title_word = title_word[0]
        title_word = re.sub(r"[^A-Za-z0-9]", "", unidecode(title_word.split()[0]))
        citekey = f"{first_last}{year}{title_word}"

    fields = {
        "author":  authors_bib,
        "title":   meta.get("title", "{Title missing}"),
        "journal": meta.get("journal"),
        "year":    year,
        "volume":  meta.get("volume"),
        "number":  meta.get("issue"),
        "pages":   pages or None,
        "doi":     meta.get("doi"),
    }

    body = ",\n  ".join(f"{k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@article{{{citekey},\n  {body}\n}}\n"


def process_html_to_bib(html_path: Path, output_dir: Path) -> Optional[Path]:
    """Read an HTML file, extract metadata, write a .bib file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bib_path = output_dir / f"{html_path.stem}.bib"

    if bib_path.is_file():
        return bib_path

    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        meta = extract_metadata(html)
        bib_path.write_text(metadata_to_biblatex(meta), encoding="utf-8")
        logger.info("BibLaTeX → %s", bib_path.name)
        return bib_path
    except Exception:
        logger.exception("Failed to extract metadata from %s", html_path)
        return None
