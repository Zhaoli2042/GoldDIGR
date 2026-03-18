"""
stirling_client.py – Clean Python wrapper for StirlingPDF's REST API.

Replaces the shell-based split_curl_template with proper error handling,
retries, and temp-file management.  The user never needs to know how
StirlingPDF's API works.

Usage:
    client = StirlingClient("http://stirling-pdf:8080")
    pages  = client.split_pages(Path("paper.pdf"))   # → list[Path]
    text   = client.pdf_to_text(Path("page_3.pdf"))  # → str
    texts  = client.split_and_extract(Path("si.pdf"))  # → list[str]  (one-shot)
"""

from __future__ import annotations
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class StirlingClient:
    """Thin, retry-aware client for StirlingPDF's REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: int = 120,
        retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Requests session with automatic retry on transient errors
        self.session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=retries,
                backoff_factor=2,
                status_forcelist=[502, 503, 504],
            )
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # ── Health check ─────────────────────────────────────────────────────
    def wait_until_ready(self, timeout: int = 120, poll: int = 5) -> bool:
        """Block until StirlingPDF responds, or raise after timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.session.get(
                    f"{self.base_url}/api/v1/info/status", timeout=5
                )
                if r.ok:
                    logger.info("StirlingPDF is ready at %s", self.base_url)
                    return True
            except requests.ConnectionError:
                pass
            time.sleep(poll)
        raise TimeoutError(
            f"StirlingPDF not reachable at {self.base_url} after {timeout}s"
        )

    # ── Split PDF into individual pages ──────────────────────────────────
    def split_pages(
        self,
        pdf_path: Path,
        output_dir: Optional[Path] = None,
        pages: str = "all",
    ) -> list[Path]:
        """
        Split a PDF into one file per page.

        Parameters
        ----------
        pdf_path : Path
            Input PDF file.
        output_dir : Path, optional
            Where to write the per-page PDFs.  Defaults to a sibling
            directory named ``{stem}_pages/``.
        pages : str
            Page spec for StirlingPDF (default "all").

        Returns
        -------
        list[Path]
            Paths to the individual page PDFs, sorted by page number.
        """
        if output_dir is None:
            output_dir = pdf_path.parent / f"{pdf_path.stem}_pages"
        output_dir.mkdir(parents=True, exist_ok=True)

        url = f"{self.base_url}/api/v1/general/split-pages"
        with open(pdf_path, "rb") as f:
            resp = self.session.post(
                url,
                files={"fileInput": (pdf_path.name, f, "application/pdf")},
                data={"pageNumbers": pages},
                timeout=self.timeout,
            )
        resp.raise_for_status()

        # Response is a ZIP containing the split PDFs
        page_paths = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in sorted(zf.namelist()):
                if name.lower().endswith(".pdf"):
                    dest = output_dir / name
                    dest.write_bytes(zf.read(name))
                    page_paths.append(dest)

        logger.info("Split %s → %d pages in %s", pdf_path.name, len(page_paths), output_dir)
        return sorted(page_paths)

    # ── Convert a single PDF (or page) to plain text ─────────────────────
    def pdf_to_text(self, pdf_path: Path) -> str:
        """
        Convert a PDF to plain text via StirlingPDF's OCR/extraction.

        Returns the extracted text as a string.
        """
        url = f"{self.base_url}/api/v1/convert/pdf/text"
        with open(pdf_path, "rb") as f:
            resp = self.session.post(
                url,
                files={"fileInput": (pdf_path.name, f, "application/pdf")},
                data={"outputFormat": "txt"},
                timeout=self.timeout,
            )
        resp.raise_for_status()
        return resp.text

    # ── One-shot: split → convert each page → return texts ───────────────
    def split_and_extract(
        self,
        pdf_path: Path,
        output_dir: Optional[Path] = None,
        cleanup_pages: bool = True,
    ) -> list[str]:
        """
        Split a PDF into pages, convert each to text, return the list.
        Optionally cleans up intermediate per-page PDFs.
        """
        page_pdfs = self.split_pages(pdf_path, output_dir)
        texts = []
        for page_pdf in page_pdfs:
            try:
                text = self.pdf_to_text(page_pdf)
                texts.append(text)
            except Exception as exc:
                logger.warning("Failed to extract text from %s: %s", page_pdf.name, exc)
                texts.append("")
            finally:
                if cleanup_pages:
                    page_pdf.unlink(missing_ok=True)

        # Clean up the pages directory if empty
        if cleanup_pages and output_dir and output_dir.exists():
            try:
                output_dir.rmdir()
            except OSError:
                pass  # not empty, leave it

        logger.info("Extracted text from %d pages of %s", len(texts), pdf_path.name)
        return texts
