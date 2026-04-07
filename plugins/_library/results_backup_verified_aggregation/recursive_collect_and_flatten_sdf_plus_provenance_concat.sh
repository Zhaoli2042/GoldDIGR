# ── SNIPPET: results_backup_verified_aggregation/recursive_collect_and_flatten_sdf_plus_provenance_concat ─
# Scheduler:   any
# Tool:        any
# Tested:      collect_auto3d_structures
# Notes: Marked as untested in README; snippet is extracted as-is.
# ────────────────────────────────────────────────────────────

import os
import shutil
from typing import List

def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def collect_sdfs_and_build_map(input_dir: str, output_dir: str) -> None:
    input_dir = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)
    summary_file_path = os.path.join(output_dir, "all_smiles_prefix_map.txt")

    print(f"Searching for files in: {input_dir}")
    print(f"Copying files to:       {output_dir}")

    ensure_dir(output_dir)

    sdf_count = 0
    mapped_count = 0
    summary_lines: List[str] = []

    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".sdf"):
                source_sdf_path = os.path.join(root, file)

                try:
                    shutil.copy2(source_sdf_path, os.path.join(output_dir, file))
                    sdf_count += 1
                except Exception as e:
                    print(f"[ERROR] Could not copy {file}: {e}")

                prefix_name = os.path.splitext(file)[0]
                smi_filename = f"{prefix_name}.smi"
                source_smi_path = os.path.join(root, smi_filename)

                if os.path.exists(source_smi_path):
                    try:
                        with open(source_smi_path, "r") as f:
                            line = f.read().strip()
                            if line:
                                summary_lines.append(line)
                                mapped_count += 1
                    except Exception as e:
                        print(f"[WARN] Found .smi for {file} but could not read it: {e}")

    if summary_lines:
        summary_lines.sort()
        with open(summary_file_path, "a") as f:
            f.write("\n".join(summary_lines) + "\n")
        print(f"Appended to summary map:  {summary_file_path}")
    else:
        print("[WARN] No accompanying .smi files found. Summary list is empty.")

    print("-" * 60)
    print(f"Processing Complete.")
    print(f"Total .sdf files copied: {sdf_count}")
    print(f"Total molecules mapped:  {mapped_count}")
