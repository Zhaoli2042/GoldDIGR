# ── SNIPPET: submission_manager_slurm_throttled/iterative_retry_until_complete_then_collect_outputs ─
# Scheduler:   slurm
# Tool:        auto3d
# Tested:      README_purdue_standby
# Notes: Extracted from README as a reusable operational pattern.
# ────────────────────────────────────────────────────────────

1) Create/activate the conda env that contains Auto3D + GPU stack (edit {{CONDA_ENV}}).
2) Run the batching/submission driver on an input file in "SMILES PREFIX" format (edit {{DEFAULT_SMILES_LIST}}):
   python {{purdue_standby_auto3d_auto_batch.py}} --batch-size {{BATCH_SIZE}} --auto-batch-size {{AUTO_BATCH_SIZE}}
3) After jobs finish, run the status aggregator pointing ORIGINAL_SMILES_PATH to the same input file:
   python {{get_auto3d_calc_status.py}}
4) Re-run the driver using the emitted failed/missing SMILES lists as new inputs until coverage is complete.
5) Collect all per-prefix .sdf files into a single directory:
   python {{collect_auto3d_structures.py}} -i {{WORKDIR}} -o {{COLLECT_DIR}}
