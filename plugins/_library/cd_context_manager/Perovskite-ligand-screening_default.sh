# ── SNIPPET: cd_context_manager/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/functions.py
# Invariants:
#   - Always restore the original working directory even if an exception occurs.
# Notes: `with cd(path): ...`
# ────────────────────────────────────────────────────────────

import os

# Context manager for changing the current working directory
class cd:
    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)
