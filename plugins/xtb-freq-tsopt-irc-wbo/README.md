# xTB Frequency → TSOPT → IRC → Spin/WBO Plugin

## Overview

This plugin processes XYZ structures extracted by golddigr through a
computational chemistry pipeline to identify and characterise transition states.

## Workflow

1. **xTB Frequency** — GFN2-xTB Hessian calculation on each XYZ file.
   Gate: imaginary frequency with |ν| > 20 cm⁻¹ indicates a candidate TS.

2. **TSOPT** — Pysisyphus RS-P-RFO transition state optimisation (xTB).
   Gate: produces `ts_final_geometry.xyz`.

3. **IRC** — Pysisyphus Euler predictor–corrector intrinsic reaction coordinate.
   Gate: produces `finished_irc.trj`, `finished_first.xyz`, `finished_last.xyz`.

4. **Spin/WBO scan** — Two-pass spin-polarised xTB energy scan + Wiberg bond
   order extraction along the IRC trajectory (`spin_wbo_scan.py`).

5. **IRC Analysis** — YARP bond-electron matrix analysis of IRC endpoints and
   trajectory frames (`yarp_results_builder.py`).

6. **Sankey** — Electron transport Sankey diagrams from the BEM time series
   (`irc_sankey_zoomsvg_fixed.py`).

## Charge / Multiplicity

- If the XYZ comment line contains charge info, it is used.
- Otherwise, charges `[-1, 0, 1]` are sampled independently (3 runs per XYZ).
- Multiplicity is auto-determined as the lowest possible for each charge.

## HPC Requirements

- SLURM scheduler
- Conda environment `another-yarp` (see `environment.yml`)
- Modules: `conda/2025.02`, `intel-mkl`, `openmpi`

## Files

- `plugin.yaml` — Machine-readable workflow manifest
- `scripts/` — Computation scripts (do not modify)
- `templates/` — Pysisyphus YAML and SLURM submission templates
- `environment.yml` — Conda environment specification
