"""
pdf_processor.py – Full PDF processing pipeline using StirlingPDF + text cleanup.

Replaces the shell scripts:
  - split_curl_template    → StirlingClient.split_and_extract()
  - remove_xyz_pagenumber  → pdf_txt_processing.initial_cleanup()
                           + pdf_txt_processing.continue_cleanup()
                           + separate_xyz.repack_xyz_blocks()

This module is the bridge between the StirlingPDF service and the
text-level XYZ extraction logic.
"""

from __future__ import annotations
import re
import logging
from pathlib import Path
from typing import Optional

from .stirling_client import StirlingClient
from .pdf_txt_processing import process_text_file

logger = logging.getLogger(__name__)

# Unicode dash normalization (replaces the sed one-liner in remove_xyz_pagenumber)
_DASH_CHARS = re.compile(r"[‐‑‒–—―⁻₋−﹣－︲︱]")


def process_pdf(
    pdf_path: Path,
    client: StirlingClient,
    output_dir: Path,
    simple_names: bool = False,
) -> dict:
    """
    Full processing pipeline for a single SI PDF:

      1. Split into pages via StirlingPDF
      2. Convert each page to text via StirlingPDF
      3. Concatenate all page texts
      4. Normalize unicode dashes → ASCII minus
      5. Run initial_cleanup() → footer removal, XYZ region extraction
      6. Run continue_cleanup() → second-pass page number removal
      7. Run repack_xyz_blocks() → individual .xyz files

    Parameters
    ----------
    pdf_path : Path
        The SI PDF file to process.
    client : StirlingClient
        A configured StirlingPDF client instance.
    output_dir : Path
        Where to write output files.

    Returns
    -------
    dict with processing results (has_xyz, n_blocks, etc.)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    # ── Step 1+2: Split PDF and extract text via StirlingPDF ─────────
    logger.info("Processing PDF: %s", pdf_path.name)
    page_texts = client.split_and_extract(pdf_path, output_dir / "pages")

    if not page_texts:
        logger.warning("No text extracted from %s", pdf_path.name)
        return {"has_xyz": False, "n_blocks": 0, "all_texts": []}

    # ── Step 3: Concatenate all page texts ───────────────────────────
    combined_text = "\n\n".join(page_texts)

    # Save the full combined text for reference
    full_path = output_dir / f"{stem}_full.txt"
    full_path.write_text(combined_text, encoding="utf-8")
    logger.info("Saved full text → %s (%d pages)", full_path.name, len(page_texts))

    # ── Step 4: Normalize unicode dashes ─────────────────────────────
    combined_text = _DASH_CHARS.sub("-", combined_text)

    # ── Steps 5–7: Cleanup + XYZ extraction ──────────────────────────
    result = process_text_file(combined_text, output_dir, stem, simple_names=simple_names)
    result["all_texts"] = page_texts

    return result


def process_pdf_from_text(
    text_path: Path,
    output_dir: Path,
    simple_names: bool = False,
) -> dict:
    """
    Process an already-extracted text file (skips StirlingPDF steps).
    Useful for re-processing or testing without the PDF service.
    """
    text = text_path.read_text(encoding="utf-8", errors="ignore")
    text = _DASH_CHARS.sub("-", text)
    return process_text_file(text, output_dir, text_path.stem, simple_names=simple_names)
