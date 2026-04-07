# GoldDIGR: Search, Download, Analyze Open-Source Chemistry Data

<div align="center">

![Logo](Logo.png)

</div>

Systematic, resumable mining of supplementary information (SI) files from
chemistry journal articles — plus an LLM-powered plugin system for running
computational workflows on the extracted structures.

## What It Does

### Part 1: Scraping Pipeline

Given a CSV of article URLs, the scraping pipeline:

1. Scrapes article HTML (handles Cloudflare challenges via Chrome CDP or headless Firefox)
2. Extracts SI download links (direct files + publisher download endpoints)
3. Downloads SI files (PDF, XYZ, CIF, MOL, DOCX, XLSX, ZIP, …)
4. Converts PDFs to text via StirlingPDF (sidecar container)
5. Cleans footers/headers, extracts XYZ coordinate blocks
6. Detects transition-state geometries
7. Extracts BibLaTeX metadata from HTML
8. Uses an LLM to pull structured computational-chemistry details

Every stage is tracked in SQLite. Re-running picks up exactly where it left off.

### Part 2: Plugin System

Once XYZ structures are extracted, the plugin system takes over. It runs on the
host (no container needed) and manages computational chemistry workflows on HPC
clusters:

| Command | What it does |
|---------|-------------|
| `plugin.py develop <path>` | Incremental test-driven development — reads your scripts, generates SLURM glue code, runs pilot tests, auto-diagnoses failures |
| `plugin.py catalog <path>` | Catalogs a plugin into a shared knowledge base with reusable snippets |
| `plugin.py diagnose <name>` | LLM-powered failure diagnosis from pilot or production job logs |
| `plugin.py probe` | Auto-detects cluster infrastructure (scheduler, modules, partitions) |
| `plugin.py list` | Lists all registered plugins |
| `plugin.py package <name>` | Builds tarballs of XYZ structures + submission scripts for cluster upload |
| `plugin.py port <name> --target <sched>` | Ports glue scripts to a different scheduler (SLURM, HTCondor, SGE, PBS) |

The core principle: **"LLM writes plumbing, never touches science."** Your
computational scripts are copied verbatim; only the glue (runner scripts, job
submission, directory wiring) is generated.

Two example plugins are included:

- **`xtb-freq-tsopt-irc-wbo`** — xTB frequency analysis → pysisyphus TSOPT → IRC → spin-polarised WBO scan → YARP bond-electron analysis → Sankey diagrams. Defined as a 6-stage pipeline in `plugin.yaml`.
- **`dft-singlepoint`** — ORCA DFT single-point + Multiwfn WBO analysis via HTCondor with containerised software.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        docker compose up                            │
│                                                                     │
│  ┌──────────────┐         ┌───────────────────────────────────┐     │
│  │ StirlingPDF  │◄────────│       Scraping Pipeline           │     │
│  │  (sidecar)   │  HTTP   │                                   │     │
│  │              │         │  CSV → Scrape HTML                │     │
│  │  split-pages │         │        → Extract SI links         │     │
│  │  pdf-to-text │         │          → Download files         │     │
│  └──────────────┘         │            → Process PDFs ────────┤     │
│                           │              → Clean text         │     │
│                           │                → LLM extract      │     │
│                           │                  → Find TS XYZ    │     │
│                           └───────────────────────────────────┘     │
│                                        │                            │
│                              ┌─────────┴──────────┐                 │
│                              │   SQLite Ledger     │                 │
│                              │  (resumable state)  │                 │
│                              └────────────────────┘                 │
└──────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼ data/output/xyz/
┌──────────────────────────────────────────────────────────────────────┐
│                    Plugin System (runs on host)                      │
│                                                                     │
│  plugin.py develop   →  read scripts, generate glue, pilot test     │
│  plugin.py package   →  bundle XYZ + scripts into tarballs          │
│  plugin.py diagnose  →  LLM-powered failure analysis                │
│  plugin.py port      →  adapt glue to SLURM / HTCondor / SGE / PBS │
│                                                                     │
│  plugins/                                                           │
│  ├── xtb-freq-tsopt-irc-wbo/   (xTB → TSOPT → IRC → WBO → Sankey) │
│  └── dft-singlepoint/          (ORCA DFT + Multiwfn WBO)           │
└──────────────────────────────────────────────────────────────────────┘
```

### Pipeline Stages (Scraping)

```
PENDING → HTML_SCRAPED → LINKS_EXTRACTED → FILES_DOWNLOADED
        → PDF_PROCESSED → TEXT_EXTRACTED → DONE
```

Any stage can fail independently without affecting other articles.

## Quick Start

### Option A: Docker Compose (simplest)

Best for batch processing when Cloudflare isn't an issue.

```bash
git clone https://github.com/Zhaoli2042/GoldDIGR.git && cd GoldDIGR

# Configure API keys
cp .env.example .env
# Edit .env with your LLM API key

# Place your article CSV
mkdir -p data/input
cp your-articles.csv data/input/articles.csv

# Run
docker compose up --build

# Or process a specific range
docker compose run pipeline python run.py --start 0 --end 100

# Check progress
docker compose run pipeline python run.py --status

# Retry failed jobs
docker compose run pipeline python run.py --retry-failed
```

### Option B: Local Chrome (recommended for Cloudflare-heavy publishers)

Best for Wiley, Elsevier, and other publishers with aggressive bot detection.
Uses your real Chrome browser with your existing cookies and login sessions.

```bash
# 1. Start StirlingPDF
docker run -p 8080:8080 stirlingtools/stirling-pdf:latest

# 2. Create a Python environment
conda create -n golddigr python=3.11 && conda activate golddigr
# or: python -m venv .venv && source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Set environment variables
export STIRLING_URL=http://localhost:8080
export OPENAI_API_KEY=sk-proj-...

# 5. Use the Chrome config
cp config.chrome.yaml config.yaml

# 6. Run (Chrome will open with your profile)
python run.py --start 0 --end 100
```

Chrome launches via CDP (Chrome DevTools Protocol) using your real profile —
Cloudflare sees a legitimate browser with real cookies. If a CAPTCHA still
appears, the pipeline will prompt you to solve it manually and retry.

> **Note:** If you have multiple Chrome profiles, set `chrome_profile_directory`
> in config.yaml to match yours (e.g., `Default`, `Profile 1`). Check with:
> `ls ~/.config/google-chrome/`

> **Important:** Chrome opens PDFs in its built-in viewer by default instead of
> downloading them. You need to change this once:
> Chrome → Settings → Privacy and security → Site settings → Additional content
> settings → PDF documents → select **"Download PDFs"**

### Option C: Local Firefox

For publishers without aggressive bot detection (ACS, RSC, etc.).

```bash
# 1. Start StirlingPDF
docker run -p 8080:8080 stirlingtools/stirling-pdf:latest

# 2. Create a Python environment
conda create -n golddigr python=3.11 && conda activate golddigr
# or: python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
export STIRLING_URL=http://localhost:8080
export OPENAI_API_KEY=sk-proj-...

# 5. Use the Firefox config
cp config.firefox-local.yaml config.yaml

# 6. Run
python run.py --start 0 --end 100
```

### Option D: Singularity/Apptainer (HPC)

```bash
# Build the SIF (one-time)
docker build -t golddigr .
apptainer build golddigr.sif docker-daemon://golddigr:latest

# Run
export OPENAI_API_KEY=sk-proj-...
./golddigr --start 0 --end 100
./golddigr --status
```

## Plugin System Usage

The plugin system runs on the host (no container). It reads extracted XYZ files
from `data/output/xyz/` and generates HPC submission packages.

### Developing a new plugin

```bash
# Point at a directory containing your scripts + plugin.yaml
python plugin.py develop plugins/xtb-freq-tsopt-irc-wbo

# This will:
#   1. Read your plugin.yaml and scripts/
#   2. Generate glue/ (runner.sh, submit scripts)
#   3. Run a pilot test on a few XYZ files
#   4. Auto-diagnose any failures
```

### Building HPC packages

```bash
# Configure your cluster (one-time)
cp cluster.yaml.example cluster.yaml
# Edit cluster.yaml with your SLURM account, partitions, modules

# Package all extracted XYZ structures for cluster submission
python plugin.py package xtb-freq-tsopt-irc-wbo --cluster cluster.yaml
```

### Plugin manifest (`plugin.yaml`)

Each plugin defines its workflow in a `plugin.yaml`:

```yaml
name: my-workflow
version: "1.0"
description: "What the workflow does"

environment:
  type: conda
  file: environment.yml

stages:
  - name: step1
    type: command
    command: "xtb {xyz} --hess --chrg {charge}"
    gate:
      type: file_exists
      file: "output.out"

  - name: step2
    type: python
    script: scripts/analyze.py
    args: "--input output.out"
```

Stages run sequentially within a single job. Gates decide whether to proceed to
the next stage or stop early.

### Other plugin commands

```bash
python plugin.py list                              # show all plugins
python plugin.py probe                             # detect cluster setup
python plugin.py diagnose my-plugin                # diagnose failures
python plugin.py catalog my-plugin                 # catalog into knowledge base
python plugin.py port my-plugin --target htcondor  # port to different scheduler
```

## Output

```
data/
├── input/
│   └── articles.csv              # your input
├── output/
│   ├── text/                     # extracted text from PDFs
│   │   └── {doi_path}/{stem}_xyz_clean.txt
│   ├── xyz/                      # transition-state structures
│   ├── biblatex/                 # BibLaTeX entries per article
│   ├── comp_details/             # LLM-extracted comp-chem JSON
│   ├── figures/                  # extracted figure metadata
│   ├── packages/                 # HPC submission tarballs (from plugin system)
│   └── pilots/                   # pilot test results (from plugin system)
├── downloads/
│   ├── html/                     # scraped article pages
│   └── files/{doi_path}/         # raw SI files (PDF, XYZ, CIF, …)
└── db/
    ├── pipeline.db               # SQLite job ledger
    └── pipeline.log              # full run log
```

## Configuration

Three example configs are provided:

| File | Browser | Profile | Headless | Use case |
|------|---------|---------|----------|----------|
| `config.yaml` | Firefox | Clean | Yes | Docker / Singularity |
| `config.chrome.yaml` | Chrome | Your profile | No | Cloudflare-heavy publishers |
| `config.firefox-local.yaml` | Firefox | Clean | Yes | Local, no Cloudflare issues |

Copy whichever fits your use case to `config.yaml`.

### Key Settings

```yaml
scraper:
  browser: chrome          # "firefox" or "chrome"
  browser_profile: auto    # "none", "auto", or explicit path
  chrome_profile_directory: Default  # Chrome profile subdirectory
  headless: false          # true for containers, false to see the browser
  interactive: true        # prompt on Cloudflare challenges
```

## Cloudflare Handling

Many publishers (especially Wiley) use Cloudflare bot detection. golddigr
handles this with a multi-tier approach:

1. **Automatic wait** — If a challenge page is detected, waits for it to
   auto-clear (often works for IP-based challenges)

2. **Chrome + user profile** — Using `browser: chrome` with `browser_profile: auto`
   launches Chrome with your real cookies and browser fingerprint. Cloudflare
   sees a legitimate browser and usually skips the challenge entirely.

3. **Agent auto-click (optional)** — A local vision model (Qwen2.5-VL) takes a
   screenshot, finds the Cloudflare checkbox, and clicks it via `xdotool`.
   Requires a GPU and extra dependencies:

   ```bash
   pip install -r requirements-agent.txt
   sudo apt install xdotool   # Linux
   ```

   Enable in config.yaml:
   ```yaml
   agent:
     enabled: true
     providers:
       - qwen-vl-local        # Qwen2.5-VL-3B (~7GB VRAM)
     model_size: 3b           # or "7b" for more accuracy (~16GB VRAM)
     device: auto
   ```

4. **Interactive fallback** — If all automated methods fail and `interactive: true`,
   the pipeline prompts you to solve the CAPTCHA manually. Type Enter to retry
   or `s` to skip the article.

5. **Cached challenge detection** — If a previously saved HTML file contains a
   Cloudflare challenge page, it's automatically deleted and re-downloaded.

## Project Structure

```
golddigr/
├── docker-compose.yml          # Two-service setup (pipeline + StirlingPDF)
├── Dockerfile                  # Python + Firefox + geckodriver
├── config.yaml                 # Default config (Docker)
├── config.chrome.yaml          # Local Chrome config
├── config.firefox-local.yaml   # Local Firefox config
├── cluster.yaml.example        # HPC cluster config template
├── .env.example                # API key template
├── run.py                      # Scraping pipeline CLI
├── plugin.py                   # Plugin system CLI (runs on host)
├── golddigr                    # Singularity/Apptainer wrapper
├── requirements.txt            # Core dependencies
├── requirements-agent.txt      # Optional: agent auto-click dependencies
├── pipeline/
│   ├── orchestrator.py         # State-machine driver
│   ├── job_db.py               # SQLite job ledger
│   ├── scraper.py              # Browser automation (Firefox + Chrome CDP)
│   ├── link_extractor.py       # SI link detection (direct + query-param URLs)
│   ├── stirling_client.py      # StirlingPDF Python wrapper
│   ├── pdf_processor.py        # PDF → text → cleanup → XYZ
│   ├── pdf_txt_processing.py   # Footer detection, header removal
│   ├── separate_xyz.py         # XYZ line detection, Gaussian conversion
│   ├── file_processors.py      # Route files by type (docx/xlsx/zip → text)
│   ├── metadata.py             # HTML meta → BibLaTeX
│   ├── figure_extractor.py     # PDF figure extraction
│   ├── cc_detector.py          # Comp-chem keyword detection + LLM
│   ├── agent/                  # Optional: automated CAPTCHA solving
│   │   ├── solver.py           # Orchestration: screenshot → model → click
│   │   ├── clicker.py          # OS cursor control (xdotool / cliclick)
│   │   └── vision/             # Vision model providers
│   │       ├── qwen_vl.py      # Qwen2.5-VL (local, default)
│   │       ├── florence.py     # Florence-2 (local, experimental)
│   │       └── api_provider.py # Claude / OpenAI API fallback
│   └── plugins/                # Plugin framework modules
│       ├── registry.py         # Plugin discovery and manifest loading
│       ├── develop.py          # Test-driven development loop
│       ├── catalog.py          # Knowledge base cataloging
│       ├── diagnose.py         # LLM failure diagnosis
│       ├── initializer.py      # Plugin scaffold generation
│       ├── packager.py         # XYZ → HPC submission tarballs
│       ├── pilot.py            # Pilot test runner
│       ├── porter.py           # Scheduler porting (SLURM ↔ HTCondor ↔ SGE)
│       ├── probe.py            # Cluster infrastructure detection
│       ├── containers.py       # Docker/Singularity utilities
│       ├── library.py          # Knowledge base functions
│       ├── samples.py          # Sample data management
│       └── ignore.py           # Ignore list management
├── plugins/                    # Example plugin workflows
│   ├── xtb-freq-tsopt-irc-wbo/ # xTB → TSOPT → IRC → WBO → Sankey
│   │   ├── plugin.yaml         # Workflow manifest (6 stages)
│   │   ├── environment.yml     # Conda environment
│   │   ├── scripts/            # User-provided computational scripts
│   │   ├── templates/          # SLURM + pysisyphus config templates
│   │   └── glue/               # Generated runner + submission scripts
│   └── dft-singlepoint/        # ORCA DFT + Multiwfn WBO via HTCondor
│       ├── README.md
│       └── scripts/            # HTCondor submission + monitoring scripts
└── data/                       # Mounted volumes (gitignored)
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `STIRLING_URL` | StirlingPDF endpoint | `http://localhost:8080` |
| `OPENAI_API_KEY` | OpenAI API key (for LLM extraction + plugin commands) | — |
| `ANTHROPIC_API_KEY` | Anthropic API key (alternative LLM provider) | — |
| `LLM_PROVIDER` | Override LLM provider from config | `openai` |
| `LLM_MODEL` | Override LLM model from config | `gpt-4o` |

## Key Design Decisions

| Problem | Approach |
|---|---|
| Tracking progress | SQLite ledger with state machine |
| PDF processing | StirlingPDF sidecar, zero config |
| Cloudflare bypass | Chrome CDP with real user profile |
| Download retries | Watchdog thread + cookie strategy loop |
| Footer removal | NLTK-based detection in `pdf_txt_processing.py` |
| File format routing | Extension + query-param detection in `link_extractor.py` |
| Configuration | Single `config.yaml` + env var overrides |
| Resumability | Automatic — SQLite tracks every stage |
| Plugin glue generation | LLM writes plumbing, never touches science |
| Scheduler portability | `plugin.py port` adapts glue to SLURM/HTCondor/SGE/PBS |

## License

MIT — see [LICENSE](LICENSE).

Also, please give our repository a ⭐ if our code helps!
