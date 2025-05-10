#!/usr/bin/env python3
"""
link_extractor.py  –  importable module or run-it-directly script.

>>> from link_extractor import extract_links_from_file
>>> links = extract_links_from_file("output.txt", base_url="https://rsc.org")
>>> print(links[:5])
"""

import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Optional
from urllib.parse import urlsplit, unquote
import requests
import sys
import mimetypes

#from test_requests_package import AU
# ----------------------------------------------------------------------
AUTO_DOWNLOAD_EXTS = {".pdf", ".xyz", ".cif", ".txt", ".xlsx", ".mol",
                      ".mol2", ".data", ".docx", ".pdb", ".zip", ".csv"}
# ----------------------------------------------------------------------
# core regular expression for href= / src=
_ATTR_RE = re.compile(
    r'''(?:href|src)=            # attribute name
        [\'"]?                   # optional opening quote
        (?P<url>[^\'"\s>]+)      # capture the URL
    ''',
    re.IGNORECASE | re.VERBOSE
)

def extract_links_from_file(
    file_path: str | Path,
    *,
    base_url: Optional[str] = None
) -> List[str]:
    """
    Return a de-duplicated, order-preserving list of links found in *file_path*.

    Parameters
    ----------
    file_path : str or pathlib.Path
        The plain-text or HTML file to scan.
    base_url : str, optional
        If provided, relative URLs are resolved against this base.

    Returns
    -------
    list[str]
        Unique links in the order they first appeared.
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    seen, links = set(), []

    for match in _ATTR_RE.finditer(text):
        url = unescape(match.group("url"))
        if base_url:
            url = urljoin(base_url, url)
        if url not in seen:
            seen.add(url)
            links.append(url)

    return links

def _deduce_filename(url: str, default: str = "download") -> str:
    """
    Turn the URL path into a safe local filename.
    """
    name = Path(unquote(urlsplit(url).path)).name or default
    return re.sub(r'[\\/*?<>|"\']', "_", name)

def _looks_like_download(url: str) -> bool:
    """
    Quick heuristic based on extension before the query string.
    """
    #path = urlsplit(url).path.lower()
    path = url
    return any(path.endswith(ext) for ext in AUTO_DOWNLOAD_EXTS)

def smart_click(url: str, *, save_dir: str | Path = ".", timeout: int = 15) -> Path | None:
    """
    GET *url*.  If it appears to be a .pdf or .xyz (by extension or MIME),
    stream it to *save_dir* and return the file path; else open in browser.

    Parameters
    ----------
    url : str
        The URL to fetch.
    save_dir : str or pathlib.Path, default "."
        Directory where downloads are stored (created if needed).
    timeout : int, default 15
        Seconds to wait before network timeout.
    """
    save_dir = Path(save_dir).expanduser().resolve()
    save_dir.mkdir(parents=True, exist_ok=True)

    heuristic_download = _looks_like_download(url)

    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()

            # Content-Type header, fallback to mimetypes for unknown types
            ctype = r.headers.get("content-type", "")
            ext = mimetypes.guess_extension(ctype.split(";")[0].strip() or "") or ""

            is_pdf  = "application/pdf" in ctype.lower() or ext == ".pdf"
            is_xyz  = ext == ".xyz" or _looks_like_download(url) and url.lower().endswith(".xyz")

            if heuristic_download or is_pdf or is_xyz:
                filename = _deduce_filename(url)
                filepath = save_dir / filename
                with filepath.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 15):  # 32 kB
                        fh.write(chunk)
                print(f"✅  Saved {filepath.name} → {filepath}")
                return filepath

            # otherwise delegate to the browser
            print(f"ℹ️  Opening in browser (content-type: {ctype or 'unknown'})")
            webbrowser.open(url)
            return None

    except requests.RequestException as exc:
        print("❌  Network or HTTP error:", exc, file=sys.stderr)
        raise


# # ----------------------------------------------------------------------
# # Optional command-line interface
# import argparse, sys
# text_string = "https://pubs.rsc.org/en/content/articlelanding/2025/cy/d5cy00187k"
# for link in extract_links_from_file("output.txt", 
#                                     base_url = text_string):
#     if ".pdf" in link:
#         print(link)
#     if ".cif" in link:
#         print(link)
