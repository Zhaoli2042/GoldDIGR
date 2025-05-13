#!/usr/bin/env python3
"""
xlsx_to_txt.py – Convert an Excel file to one or more .txt files.

• Each worksheet becomes      <workbook-name>_<sheet-name>.txt
• Tab is the default column separator (override with `sep=`).
• Blank cells are written as empty strings (override with `na_rep=`).
"""

from pathlib import Path
import pandas as pd

def XLSX_TO_TXT(source_file, out_dir=None, *, sep="\t", na_rep=""):
    xlsx_path = source_file

    # Where to drop the .txt files
    out_dir = Path(out_dir or xlsx_path.parent).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read the workbook once and iterate over its sheet names
    wb = pd.ExcelFile(xlsx_path)          # uses openpyxl under the hood
    for sheet in wb.sheet_names:
        df = wb.parse(sheet)

        # Make the sheet’s name filename-safe
        safe_sheet = "".join(c if c.isalnum() or c in "-_" else "_" for c in sheet)

        out_file = out_dir / f"{xlsx_path.stem}_{safe_sheet}.txt"
        df.to_csv(out_file, sep=sep, index=False, na_rep=na_rep)
        print(f"Wrote {out_file}")

# ---TEST---
# FILE: Path = Path("41557_2023_1383_MOESM11_ESM.xlsx").expanduser().resolve()
# XLSX_TO_TXT(FILE)
