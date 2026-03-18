"""
pipeline.figure_extractor – Extract figures and images from PDFs.

Uses PyMuPDF (fitz) to:
  1. Extract embedded images (photos, plots, spectra)
  2. Render full pages as PNG (fallback for vector figures)

Output structure per PDF:
  figures/{job_id}/{pdf_stem}/
    embedded/            — extracted raster images (fig_001.png, ...)
    pages/               — full-page renders (page_001.png, ...)
    manifest.json        — metadata: source PDF, image count, sizes, pages
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum image dimensions to keep (skip tiny icons, logos, decorations)
_MIN_WIDTH = 100
_MIN_HEIGHT = 100
# Minimum image bytes (skip 1x1 spacer GIFs, etc.)
_MIN_BYTES = 2048
# DPI for full-page rendering
_PAGE_DPI = 200


def extract_figures(
    pdf_path: Path,
    output_dir: Path,
    *,
    extract_embedded: bool = True,
    render_pages: bool = True,
    min_width: int = _MIN_WIDTH,
    min_height: int = _MIN_HEIGHT,
    min_bytes: int = _MIN_BYTES,
    page_dpi: int = _PAGE_DPI,
) -> Dict[str, Any]:
    """
    Extract figures from a PDF file.

    Args:
        pdf_path:          Path to the PDF file
        output_dir:        Base output directory for this PDF
        extract_embedded:  Extract raster images embedded in the PDF
        render_pages:      Render each page as a full-page PNG
        min_width/height:  Minimum dimensions to keep an embedded image
        min_bytes:         Minimum file size to keep an embedded image
        page_dpi:          Resolution for full-page renders

    Returns:
        Dict with extraction results:
          n_embedded: int, n_pages: int, figures: list of dicts
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF not installed (pip install pymupdf). Skipping figure extraction.")
        return {"n_embedded": 0, "n_pages": 0, "figures": [], "error": "pymupdf not installed"}

    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        return {"n_embedded": 0, "n_pages": 0, "figures": [], "error": "file not found"}

    output_dir = Path(output_dir)
    embedded_dir = output_dir / "embedded"
    pages_dir = output_dir / "pages"

    result: Dict[str, Any] = {
        "source_pdf": str(pdf_path.name),
        "n_embedded": 0,
        "n_pages": 0,
        "figures": [],
    }

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning("Failed to open PDF %s: %s", pdf_path.name, e)
        result["error"] = str(e)
        return result

    # ── Extract embedded images ───────────────────────────────────────
    if extract_embedded:
        embedded_dir.mkdir(parents=True, exist_ok=True)
        seen_xrefs = set()
        fig_idx = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]

                # Skip duplicates (same image referenced on multiple pages)
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base_image = doc.extract_image(xref)
                except Exception:
                    continue

                if not base_image:
                    continue

                img_bytes = base_image.get("image")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)
                ext = base_image.get("ext", "png")

                # Filter out tiny images
                if width < min_width or height < min_height:
                    continue
                if img_bytes and len(img_bytes) < min_bytes:
                    continue

                fig_idx += 1
                # Normalize extension
                if ext in ("jpeg", "jpg"):
                    ext = "jpg"
                elif ext not in ("png", "tiff", "tif", "bmp"):
                    ext = "png"

                fig_name = f"fig_{fig_idx:03d}.{ext}"
                fig_path = embedded_dir / fig_name

                if img_bytes:
                    fig_path.write_bytes(img_bytes)
                    result["figures"].append({
                        "type": "embedded",
                        "file": f"embedded/{fig_name}",
                        "page": page_num + 1,
                        "width": width,
                        "height": height,
                        "bytes": len(img_bytes),
                    })

        result["n_embedded"] = fig_idx
        if fig_idx:
            logger.info("%s: extracted %d embedded images", pdf_path.name, fig_idx)

    # ── Render full pages ─────────────────────────────────────────────
    if render_pages:
        pages_dir.mkdir(parents=True, exist_ok=True)

        for page_num in range(len(doc)):
            page = doc[page_num]

            try:
                # Render at specified DPI
                mat = fitz.Matrix(page_dpi / 72, page_dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)

                page_name = f"page_{page_num + 1:03d}.png"
                page_path = pages_dir / page_name
                pix.save(str(page_path))

                result["figures"].append({
                    "type": "page_render",
                    "file": f"pages/{page_name}",
                    "page": page_num + 1,
                    "width": pix.width,
                    "height": pix.height,
                })
            except Exception as e:
                logger.warning("%s page %d render failed: %s", pdf_path.name, page_num + 1, e)

        result["n_pages"] = len(doc)

    doc.close()

    # ── Write manifest ────────────────────────────────────────────────
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def extract_figures_from_directory(
    pdf_dir: Path,
    output_base: Path,
    **kwargs,
) -> List[Dict[str, Any]]:
    """Extract figures from all PDFs in a directory."""
    results = []
    pdf_dir = Path(pdf_dir)

    if not pdf_dir.is_dir():
        return results

    for pdf_file in sorted(pdf_dir.rglob("*.pdf")):
        out_dir = output_base / pdf_file.stem
        result = extract_figures(pdf_file, out_dir, **kwargs)
        results.append(result)

    return results
