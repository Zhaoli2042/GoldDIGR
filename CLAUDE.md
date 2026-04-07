# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

GoldDIGR is a Python pipeline for mining supplementary information (SI) files from chemistry journal articles. It scrapes article HTML, extracts SI download links, downloads files, converts PDFs to text via StirlingPDF, extracts XYZ coordinate blocks and transition-state geometries, pulls BibLaTeX metadata, and uses an LLM for structured computational-chemistry detail extraction. All state is tracked in SQLite for full resumability.

## Running the Pipeline

```bash
# Docker (simplest)
docker compose up --build
docker compose run pipeline python run.py --start 0 --end 100

# Local (requires StirlingPDF running separately)
docker run -p 8080:8080 stirlingtools/stirling-pdf:latest
pip install -r requirements.txt
export STIRLING_URL=http://localhost:8080 OPENAI_API_KEY=sk-proj-...
python run.py --start 0 --end 100

# Status and retry
python run.py --status
python run.py --retry-failed
```

## Plugin System (runs on host, no container)

```bash
python plugin.py develop <path>    # incremental test-driven development
python plugin.py catalog <path>    # catalog into knowledge base
python plugin.py diagnose <name>   # LLM failure diagnosis
python plugin.py probe             # detect cluster infrastructure
python plugin.py list              # list registered plugins
```

Or via `run.py`: `python run.py plugin <subcommand> [args]`

Two example plugins exist in `plugins/`: `xtb-freq-tsopt-irc-wbo` (xTB frequency/TSOPT/IRC/WBO pipeline) and `dft-singlepoint`.

## Architecture

**Entry points:** `run.py` (main CLI), `plugin.py` (plugin CLI), `golddigr` (Singularity/Apptainer wrapper).

**Pipeline state machine** (in `pipeline/orchestrator.py`):
```
PENDING → HTML_SCRAPED → LINKS_EXTRACTED → FILES_DOWNLOADED
        → PDF_PROCESSED → TEXT_EXTRACTED → DONE
```
Each stage is idempotent. Any stage can fail independently without affecting other articles (transitions to FAILED).

**Key modules in `pipeline/`:**
- `orchestrator.py` — `Pipeline` class drives the state machine; `PipelineConfig` resolves `config.yaml` with `${ENV_VAR:-default}` syntax
- `job_db.py` — SQLite ledger with `JobStatus` enum and strict transition rules
- `scraper.py` — Selenium-based browser automation (Firefox + Chrome CDP)
- `link_extractor.py` — SI link detection from HTML (direct files + publisher download endpoints)
- `stirling_client.py` — HTTP client for StirlingPDF sidecar (PDF split/text extraction)
- `pdf_processor.py` → `pdf_txt_processing.py` → `separate_xyz.py` — PDF-to-text-to-XYZ chain
- `file_processors.py` — Routes non-PDF files (docx, xlsx, zip) through appropriate handlers
- `metadata.py` — HTML meta tags → BibLaTeX; DOI extraction and path conversion
- `cc_detector.py` — Keyword-based comp-chem detection + LLM extraction
- `agent/` — Optional automated CAPTCHA solving via vision models (Qwen2.5-VL, Florence-2, or API)
- `plugins/_utils.py` — Shared LLM client, interactive prompts, and output parsing for plugin modules
- `plugins/registry.py` — Plugin discovery, manifest loading, validation
- `plugins/develop.py` — Incremental test-driven plugin development
- `plugins/catalog.py` — Knowledge base cataloging
- `plugins/diagnose.py` — LLM-powered failure diagnosis
- `plugins/packager.py` — XYZ → HPC submission tarballs
- `plugins/porter.py` — Scheduler porting (SLURM ↔ HTCondor ↔ SGE ↔ PBS)

**Configuration:** Single `config.yaml` with env var overrides. Three example configs provided for Docker, local Chrome, and local Firefox.

**Dependencies:** `requirements.txt` (core), `requirements-agent.txt` (optional CAPTCHA agent with GPU).

## Environment Variables

- `STIRLING_URL` — StirlingPDF endpoint (default: `http://localhost:8080`)
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — LLM provider keys
- `LLM_PROVIDER` / `LLM_MODEL` — override LLM settings from config

## Data Layout

All data lives under `data/` (gitignored, mounted as Docker volumes):
- `data/input/articles.csv` — input CSV with `ArticleURL` column
- `data/downloads/html/` and `data/downloads/files/{doi_path}/` — raw downloads
- `data/output/text/`, `xyz/`, `biblatex/`, `comp_details/`, `figures/` — processed outputs
- `data/db/pipeline.db` — SQLite job ledger
