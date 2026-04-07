# ── SNIPPET: xtb_spin_energy_tblite_driver/xTB-wbo-scan-Slurm_default ─
# Scheduler:   any
# Tool:        xtb
# Tested:      {{PLUGIN_NAME}}
# Invariants:
#   - Uses --spinpol --tblite for the spin scan energy pass.
#   - Writes stdout+stderr to a namespace-specific .out file in workdir.
#   - Parses HOMO-LUMO gap from 'HOMO-LUMO gap ... eV' and energy from last 'TOTAL ENERGY ... Eh'.
#   - Non-zero return code raises RuntimeError pointing to the .out file.
# Notes: Namespace includes stem + UHF + SPIN to avoid collisions.
# ────────────────────────────────────────────────────────────

import re, subprocess
from pathlib import Path

def run_xtb_energy_tblite(xyz_path, charge, uhf, workdir, acc=0.2, maxiter=500):
    ns = f"{Path(xyz_path).stem}_UHF{uhf}_SPIN"
    cmd = [
        "xtb", xyz_path, "--scc",
        "--spinpol", "--tblite",
        "--chrg", str(charge), "--uhf", str(uhf),
        "--acc", str(acc), "--iterations", str(maxiter),
        "--namespace", ns
    ]
    out_file = Path(workdir) / f"{ns}.out"
    with open(out_file, "w") as fout:
        proc = subprocess.run(cmd, stdout=fout, stderr=subprocess.STDOUT, cwd=workdir)
    if proc.returncode != 0:
        raise RuntimeError(f"xTB(spin) failed for {xyz_path} UHF={uhf} (see {out_file})")

    energy_Eh, gap_eV = None, None
    with open(out_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    for ln in lines:
        if "HOMO-LUMO gap" in ln:
            m = re.search(r"HOMO-LUMO gap\s+([-\d\.Ee+]+)\s*eV", ln)
            if m: gap_eV = float(m.group(1)); break
    for ln in reversed(lines):
        if "TOTAL ENERGY" in ln.upper():
            m = re.search(r"TOTAL ENERGY\s+([-\d\.Ee+]+)\s*Eh", ln, re.I)
            if m: energy_Eh = float(m.group(1)); break
    return {"energy_Eh": energy_Eh, "gap_eV": gap_eV, "stdout_file": str(out_file)}
