"""
orchestrator.py – Main pipeline driver.

Reads the job ledger, picks up articles at whatever state they're in,
and advances them through the pipeline:

    PENDING → HTML_SCRAPED → LINKS_EXTRACTED → FILES_DOWNLOADED
            → PDF_PROCESSED → TEXT_EXTRACTED → DONE

Each stage is idempotent: re-running the pipeline skips completed work.
"""

from __future__ import annotations
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from .job_db import JobDB, JobStatus
from .scraper import scrape_html, download_file
from .link_extractor import extract_si_links
from .stirling_client import StirlingClient
from .pdf_processor import process_pdf, process_pdf_from_text
from .pdf_txt_processing import pdf_txt_cleanup
from .file_processors import route_files
from .metadata import process_html_to_bib, extract_doi, doi_to_path
from .cc_detector import has_cc_content, flag_cc_pages, extract_cc_details
from .separate_xyz import repack_xyz_blocks
from .figure_extractor import extract_figures

logger = logging.getLogger(__name__)


class PipelineConfig:
    """Load and resolve config.yaml with environment variable overrides."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            raw = f.read()
        # Resolve ${ENV_VAR:-default} patterns
        import re
        def _resolve(m):
            var, default = m.group(1), m.group(2) or ""
            return os.environ.get(var, default)
        raw = re.sub(r"\$\{(\w+):-([^}]*)\}", _resolve, raw)
        raw = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), raw)
        self.cfg = yaml.safe_load(raw)

    def __getitem__(self, key):
        return self.cfg[key]

    def get(self, *keys, default=None):
        node = self.cfg
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node


class Pipeline:
    """
    The main pipeline orchestrator.

    Usage:
        pipeline = Pipeline("config.yaml")
        pipeline.run(start=0, end=100)
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = PipelineConfig(config_path)

        # Ensure all output directories exist
        for key in ("html_dir", "download_dir", "text_dir", "xyz_dir",
                     "figures_dir", "biblatex_dir", "comp_details_dir"):
            Path(self.config["paths"][key]).mkdir(parents=True, exist_ok=True)

        # Job ledger
        self.db = JobDB(self.config["paths"]["db_path"])

        # StirlingPDF client
        stirling_url = self.config.get("stirling", "base_url",
                                        default="http://localhost:8080")
        self.stirling = StirlingClient(
            base_url=stirling_url,
            timeout=self.config.get("stirling", "timeout", default=120),
            retries=self.config.get("stirling", "retries", default=3),
        )

    # ── Load URLs from CSV into the job ledger ───────────────────────────
    def load_articles(self, csv_path: Optional[str] = None, start: int = 0,
                      end: Optional[int] = None) -> int:
        csv_path = csv_path or self.config["input"]["csv_path"]
        url_col = self.config["input"]["url_column"]

        df = pd.read_csv(csv_path)
        if end is None:
            end = len(df)

        urls = [(i, row[url_col]) for i, row in df.iloc[start:end].iterrows()
                if pd.notna(row[url_col])]
        added = self.db.load_urls(urls)
        logger.info("Loaded %d new articles (range %d–%d)", added, start, end)
        return added

    # ── Main run loop ────────────────────────────────────────────────────
    def run(self, start: int = 0, end: Optional[int] = None,
            batch_size: int = 50) -> None:
        """Run the full pipeline on all pending/incomplete jobs."""
        self.load_articles(start=start, end=end)

        # Wait for StirlingPDF to be ready
        try:
            self.stirling.wait_until_ready(timeout=120)
        except TimeoutError:
            logger.error("StirlingPDF not available — PDF processing will be skipped")

        # Process each non-terminal state
        stages = [
            (JobStatus.PENDING,          self._stage_scrape_html),
            (JobStatus.HTML_SCRAPED,     self._stage_extract_links),
            (JobStatus.LINKS_EXTRACTED,  self._stage_download_files),
            (JobStatus.FILES_DOWNLOADED, self._stage_process_pdfs),
            (JobStatus.PDF_PROCESSED,    self._stage_extract_text),
            (JobStatus.TEXT_EXTRACTED,    self._stage_finalize),
        ]

        for status, handler in stages:
            jobs = self.db.get_jobs(status)
            if not jobs:
                continue
            logger.info("Processing %d jobs at stage %s", len(jobs), status.value)
            for job in jobs:
                try:
                    handler(job)
                except Exception as exc:
                    logger.exception("Job %d failed at %s", job["id"], status.value)
                    self.db.fail(job["id"], str(exc))

        # Print summary
        summary = self.db.summary()
        logger.info("Pipeline summary: %s", summary)

    # ── Stage 1: Scrape article HTML ─────────────────────────────────────
    def _stage_scrape_html(self, job) -> None:
        job_id, url = job["id"], job["url"]
        html_dir = Path(self.config["paths"]["html_dir"])
        output = html_dir / f"{job_id}.html"

        if output.is_file():
            self.db.advance(job_id, JobStatus.HTML_SCRAPED, html_path=str(output))
            return

        scrape_html(
            url, output,
            headless=self.config.get("scraper", "headless", default=True),
            timeout=self.config.get("scraper", "page_load_timeout", default=20),
            interactive=self.config.get("scraper", "interactive", default=False),
            browser=self.config.get("scraper", "browser", default="firefox"),
            browser_profile=self.config.get("scraper", "browser_profile", default=None),
            chrome_profile_directory=self.config.get("scraper", "chrome_profile_directory", default=None),
        )
        self.db.advance(job_id, JobStatus.HTML_SCRAPED, html_path=str(output))

        # Politeness delay
        delay = self.config.get("scraper", "delay_between_articles", default=20)
        time.sleep(delay)

    # ── Stage 2: Extract SI links from HTML ──────────────────────────────
    def _stage_extract_links(self, job) -> None:
        job_id = job["id"]
        html_path = Path(job["html_path"])

        if not html_path.is_file():
            self.db.fail(job_id, f"HTML file missing: {html_path}")
            return

        html_content = html_path.read_text(encoding="utf-8", errors="ignore")

        # Extract DOI from HTML
        doi = extract_doi(html_content)
        if doi:
            logger.info("Job %d: DOI = %s", job_id, doi)
        else:
            logger.warning("Job %d: No DOI found in HTML, using job_id as folder name", job_id)

        # Also extract BibLaTeX while we have the HTML
        biblatex_dir = Path(self.config["paths"]["biblatex_dir"])
        process_html_to_bib(html_path, biblatex_dir)

        links = extract_si_links(html_path, base_url=job["url"])
        self.db.advance(
            job_id, JobStatus.LINKS_EXTRACTED,
            si_links=json.dumps(links),
            doi=doi,
        )

        if not links:
            extra_delay = self.config.get("scraper", "delay_on_empty_links", default=60)
            logger.info("No SI links for job %d, extra delay %ds", job_id, extra_delay)
            time.sleep(extra_delay)

    # ── Stage 3: Download SI files ───────────────────────────────────────
    def _stage_download_files(self, job) -> None:
        job_id = job["id"]
        links = json.loads(job["si_links"] or "[]")

        if not links:
            # No files to download — skip ahead
            self.db.advance(job_id, JobStatus.FILES_DOWNLOADED)
            return

        # Use DOI-based folder if available, fall back to job_id
        doi = job["doi"] if "doi" in job.keys() else None
        if doi:
            folder_name = doi_to_path(doi)
        else:
            folder_name = str(job_id)

        download_dir = Path(self.config["paths"]["download_dir"]) / folder_name
        strategies = self.config.get("scraper", "cookie_strategies",
                                      default=["", "?cookieSet=0"])

        for link in links:
            result = download_file(
                link, download_dir,
                headless=self.config.get("scraper", "headless", default=True),
                timeout=self.config.get("scraper", "download_timeout", default=30),
                strategies=strategies,
                browser=self.config.get("scraper", "browser", default="firefox"),
                browser_profile=self.config.get("scraper", "browser_profile", default=None),
                chrome_profile_directory=self.config.get("scraper", "chrome_profile_directory", default=None),
            )
            if result:
                suffix = result.suffix.lower().lstrip(".")
                self.db.add_download(job_id, link, str(result), suffix)

            time.sleep(2)  # brief delay between downloads

        self.db.advance(job_id, JobStatus.FILES_DOWNLOADED)

        # Post-article cooldown (matches original 30s in finally block)
        delay = self.config.get("scraper", "delay_after_downloads", default=30)
        time.sleep(delay)

    # ── Stage 4: Process PDFs + route other file types ──────────────────
    def _stage_process_pdfs(self, job) -> None:
        job_id = job["id"]
        doi = job["doi"] if "doi" in job.keys() else None
        folder_name = doi_to_path(doi) if doi else str(job_id)

        downloads = self.db.get_downloads(job_id, file_type="pdf")
        text_dir = Path(self.config["paths"]["text_dir"]) / folder_name
        figures_dir = Path(self.config["paths"]["figures_dir"]) / folder_name

        for dl in downloads:
            pdf_path = Path(dl["local_path"])
            if not pdf_path.is_file():
                continue

            # ── Text extraction (via Stirling) ────────────────────────
            output_subdir = text_dir / pdf_path.stem
            try:
                result = process_pdf(pdf_path, self.stirling, output_subdir)
                self.db.mark_download_processed(dl["id"])
                if result.get("has_xyz"):
                    logger.info(
                        "Job %d: %s → %d XYZ blocks",
                        job_id, pdf_path.name, result.get("n_blocks", 0),
                    )
            except Exception as exc:
                logger.warning("PDF processing failed for %s: %s", pdf_path, exc)

            # ── Figure extraction (native, no Stirling) ───────────────
            try:
                fig_out = figures_dir / pdf_path.stem
                fig_result = extract_figures(pdf_path, fig_out)
                n_embedded = fig_result.get("n_embedded", 0)
                n_pages = fig_result.get("n_pages", 0)
                if n_embedded:
                    logger.info(
                        "Job %d: %s → %d figures, %d page renders",
                        job_id, pdf_path.name, n_embedded, n_pages,
                    )
            except Exception as exc:
                logger.warning("Figure extraction failed for %s: %s", pdf_path, exc)

        # Also route non-PDF files (xyz, docx, xlsx, zip) through handlers
        dl_dir = Path(self.config["paths"]["download_dir"]) / folder_name
        if dl_dir.is_dir():
            route_files(dl_dir)

        self.db.advance(job_id, JobStatus.PDF_PROCESSED)

    # ── Stage 5: Detect CC content and extract via LLM ───────────────────
    def _stage_extract_text(self, job) -> None:
        job_id = job["id"]
        doi = job["doi"] if "doi" in job.keys() else None
        folder_name = doi_to_path(doi) if doi else str(job_id)

        text_dir = Path(self.config["paths"]["text_dir"]) / folder_name
        comp_dir = Path(self.config["paths"]["comp_details_dir"])

        # Find all extracted text files
        if text_dir.exists():
            for txt_file in text_dir.rglob("*_full.txt"):
                content = txt_file.read_text(encoding="utf-8", errors="ignore")

                if has_cc_content(content):
                    logger.info("CC content detected in %s", txt_file)
                    try:
                        details = extract_cc_details(content)
                        out = comp_dir / folder_name / f"{txt_file.stem}_comp.json"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_text(json.dumps(details, indent=2), encoding="utf-8")
                    except Exception as exc:
                        logger.warning("LLM extraction failed for %s: %s", txt_file, exc)

        # Also repack any raw .xyz files that were downloaded directly
        dl_dir = Path(self.config["paths"]["download_dir"]) / folder_name
        if dl_dir.is_dir():
            for xyz_file in dl_dir.rglob("*.xyz"):
                try:
                    repack_xyz_blocks(xyz_file)
                except Exception as exc:
                    logger.warning("XYZ repack failed for %s: %s", xyz_file, exc)

        # ── Collect all XYZ files into DOI/si_stem/ structure ─────────
        # Final layout: xyz_dir/<DOI>/<si_stem>/<idx>_<name>.xyz
        #   e.g., xyz_dir/10.1021/jacs.4c07999/ja4c07999_si_001/01_TS1.xyz
        xyz_root = Path(self.config["paths"]["xyz_dir"])
        xyz_doi_dir = xyz_root / folder_name
        xyz_doi_dir.mkdir(parents=True, exist_ok=True)
        collected = 0

        # From text extraction (PDF → txt → XYZ blocks)
        # text_dir layout: <DOI>/<pdf_stem>/<pdf_stem>_blocks/*.xyz
        # The pdf_stem IS the SI filename, which becomes the subfolder
        if text_dir.exists():
            for xyz_file in text_dir.rglob("*.xyz"):
                # Determine SI stem from the path
                # Typical: text_dir/si_stem/si_stem_blocks/01_name.xyz
                #       or text_dir/si_stem/some_repacked.xyz
                rel = xyz_file.relative_to(text_dir)
                parts = rel.parts
                if len(parts) >= 2:
                    si_stem = parts[0]  # first subfolder = SI filename stem
                else:
                    si_stem = "misc"

                dest_dir = xyz_doi_dir / si_stem
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / xyz_file.name
                if not dest.exists():
                    shutil.copy2(xyz_file, dest)
                    collected += 1

        # From direct downloads (xyz files downloaded as-is)
        if dl_dir.is_dir():
            for xyz_file in dl_dir.rglob("*.xyz"):
                # Use the parent folder name as SI stem, or filename stem
                rel = xyz_file.relative_to(dl_dir)
                if len(rel.parts) >= 2:
                    si_stem = rel.parts[0]
                else:
                    si_stem = xyz_file.stem  # direct download, use its name

                dest_dir = xyz_doi_dir / si_stem
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / xyz_file.name
                if not dest.exists():
                    shutil.copy2(xyz_file, dest)
                    collected += 1

        if collected:
            logger.info(
                "Job %d: collected %d XYZ files → %s",
                job_id, collected, xyz_doi_dir,
            )

        self.db.advance(job_id, JobStatus.TEXT_EXTRACTED)

    # ── Stage 6: Mark complete ───────────────────────────────────────────
    def _stage_finalize(self, job) -> None:
        self.db.advance(job["id"], JobStatus.DONE)
        logger.info("Job %d complete", job["id"])
