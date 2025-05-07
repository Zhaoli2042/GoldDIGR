import pandas as pd
import glob
import os

# Define the folder where the CSV files are stored.
folder_path = "./"  # Update this to your folder path

# Get the list of all CSV files in the folder.
csv_files = glob.glob(os.path.join(folder_path, "*.csv"))

# List to hold individual DataFrames from each CSV file.
df_list = []

# Process each file.
for count, file in enumerate(csv_files):
    #if count > 3: break
    # Extract the base name of the file.
    filename = os.path.basename(file)
    print(filename)
    # Example filename format: "PoPCites-Transmetalation-Organometallics.csv"
    # Splitting by '-' and selecting the second element gives the reaction class.
    try:
        reaction_class = filename.split("-")[1]
    except IndexError:
        print(f"Filename {filename} does not match the expected format.")
        continue
    
    # Read the CSV file.
    df = pd.read_csv(file)
    
    # Add the reaction class to a new column.
    # We store it as a list initially so that merging later works smoothly.
    df['Reaction_Class'] = [[reaction_class]] * len(df)
    
    df_list.append(df)

# Concatenate all the data into a single DataFrame.
combined_df = pd.concat(df_list, ignore_index=True)

# Group by DOI and aggregate the reaction classes.
# This step groups entries with the same DOI and merges their reaction classes into a unique list.
def merge_reaction_classes(series):
    # Flatten the list of lists and get unique reaction classes.
    classes = set([item for sublist in series for item in sublist])
    return list(classes)

# from itertools import chain

# # Group by DOI and aggregate the 'Reaction_Class' column:
# final_df = (
#     combined_df.groupby("DOI", as_index=False)
#     .agg({
#         "Reaction_Class": lambda x: list(set(chain.from_iterable(x)))
#     })
# )
#final_df = combined_df.groupby("DOI", as_index=False)

# Initialize an empty dictionary to store DOI and corresponding reaction classes.
doi_dict = {}
# List of additional columns to preserve.
other_columns = ["Title", "Year", "Cites", "Abstract"]
# Iterate over each row of the combined DataFrame.
for _, row in combined_df.iterrows():
    doi = row["ArticleURL"]
    # If this DOI hasn't been encountered, add it to the dictionary.
    if doi not in doi_dict:
        # Use a set for Reaction_Class to avoid duplicates.
        doi_dict[doi] = {
            "Reaction_Class": set(row["Reaction_Class"]),
        }
        # For other columns, simply store the value from the first occurrence.
        for col in other_columns:
            doi_dict[doi][col] = row[col]
    else:
        # If the DOI is already in the dictionary, update the Reaction_Class set.
        doi_dict[doi]["Reaction_Class"].update(row["Reaction_Class"])
        # If you want to check consistency for other columns, this is where you'd do it.
        # For now, we'll assume the first occurrence is correct.

# Convert the dictionary into a DataFrame.
final_data = {
    "ArticleURL": [],
    "Reaction_Class": [],
}
for col in other_columns:
    final_data[col] = []

for doi, info in doi_dict.items():
    final_data["ArticleURL"].append(doi)
    # Convert the set to a list for Reaction_Class.
    final_data["Reaction_Class"].append(list(info["Reaction_Class"]))
    for col in other_columns:
        final_data[col].append(info[col])

final_df = pd.DataFrame(final_data)

# Optionally, if you want to merge additional columns from the original CSVs,
# you might need to decide how to aggregate them (e.g., first, list, etc.)

# Saving the result to a new CSV file.
final_df.to_csv("merged_URL_reaction_class.csv", index=False)

print("Processing complete. The merged CSV has been saved as 'merged_DOI_reaction_class.csv'.")
