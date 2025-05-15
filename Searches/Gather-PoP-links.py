import pandas as pd
import glob
import os
import sys

def save_with_new_entries(df: pd.DataFrame, output_filename: str) -> None:
    """Write *df* to *output_filename*.

    If *output_filename* already exists, compare the *ArticleURL* column and
    write only the brand‑new rows (those whose ArticleURL is **not** present in
    the existing file) into **new-*output_filename*** instead of touching the
    original file.
    """
    if os.path.exists(output_filename):
        print(f"[INFO] Existing file '{output_filename}' detected – checking for new links…")
        existing_df = pd.read_csv(output_filename)
        new_rows = df[~df["ArticleURL"].isin(existing_df["ArticleURL"])]

        if new_rows.empty:
            print("[INFO] No new ArticleURL entries found – nothing to write.")
            return

        new_filename = f"new-{output_filename}"
        new_rows.to_csv(new_filename, index=False)
        print(f"[SUCCESS] {len(new_rows)} new rows written to '{new_filename}'.")
    else:
        df.to_csv(output_filename, index=False)
        print(f"[SUCCESS] Output written to '{output_filename}'.")

# Get folder path from command-line argument
if len(sys.argv) < 2:
    print("Usage: python merge_csvs.py <folder_path>")
    sys.exit(1)

folder_path = sys.argv[1]

# Recursively get all CSV files in the folder and its subfolders.
csv_files = glob.glob(os.path.join(folder_path, "**", "*.csv"), recursive=True)

# List to hold individual DataFrames from each CSV file.
df_list = []

# Process each file.
for count, file in enumerate(csv_files):
    filename = os.path.basename(file)
    print(f"Processing: {filename}")
    try:
        reaction_class = filename.split("-")[1]
    except IndexError:
        print(f"Filename {filename} does not match the expected format.")
        continue
    
    df = pd.read_csv(file)
    df['Reaction_Class'] = [[reaction_class]] * len(df)
    df_list.append(df)

# Concatenate all the data into a single DataFrame.
combined_df = pd.concat(df_list, ignore_index=True)

# Initialize dictionary to group by DOI (or URL).
doi_dict = {}
other_columns = ["Title", "Year", "Cites", "Abstract"]

for _, row in combined_df.iterrows():
    doi = row["ArticleURL"]
    if doi not in doi_dict:
        doi_dict[doi] = {
            "Reaction_Class": set(row["Reaction_Class"]),
        }
        for col in other_columns:
            doi_dict[doi][col] = row[col]
    else:
        doi_dict[doi]["Reaction_Class"].update(row["Reaction_Class"])

# Convert the dictionary to a DataFrame.
final_data = {
    "ArticleURL": [],
    "Reaction_Class": [],
}
for col in other_columns:
    final_data[col] = []

for doi, info in doi_dict.items():
    final_data["ArticleURL"].append(doi)
    final_data["Reaction_Class"].append(list(info["Reaction_Class"]))
    for col in other_columns:
        final_data[col].append(info[col])

final_df = pd.DataFrame(final_data)

# Determine prefix based on folder_path.
prefix = ""
basename = os.path.basename(os.path.normpath(folder_path))
if basename and basename != ".":
    prefix = f"{basename}_"

# Save the final DataFrame to CSV.
output_filename = f"{prefix}merged_URL_reaction_class.csv"
save_with_new_entries(final_df, output_filename)

print(f"Processing complete. The merged CSV has been saved as '{output_filename}'.")
