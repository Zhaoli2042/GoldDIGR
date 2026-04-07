# ── SNIPPET: timestamped_logger/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/functions.py
# Invariants:
#   - Log filename includes a timestamp to avoid overwriting prior runs.
#   - write() must forward to both terminal and file.
# Notes: `sys.stdout = Logger('run_name')`
# ────────────────────────────────────────────────────────────

import sys
import datetime

# General logger
class Logger(object):
    def __init__(self,logname):
        self.terminal = sys.stdout
        now = datetime.datetime.now() 
        d = '{}-{}-{}_{}{}{}'.format(now.year, now.month, now.day, now.hour, now.minute, now.second)
        self.log = open(logname+'.'+d+'.log', "w")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)  

    def flush(self):
        pass
