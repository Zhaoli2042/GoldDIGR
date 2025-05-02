import pandas as pd

primary_corpus = pd.read_csv("primary_corpus.csv")
second_corpus = pd.read_csv("secondary_corpus.csv")

corpus = pd.concat([primary_corpus, second_corpus], ignore_index=True, sort=False)

doi_links = corpus['doi']

suffix      = corpus["doi"].str.split("/").str[-1]   # part after the last “/”
first_is_le = suffix.str[0].str.isalpha()        # first char is a letter
first_is_not_S    = ~suffix.str[0].str.lower().eq("s")
second_is_d = suffix.str[1].str.isdigit()        # second char is a digit
no_bad_characters = ~suffix.str.contains(r'[_\-,\.]')# 3️⃣ none of _ - . ,
mask   = (first_is_le & first_is_not_S 
          & second_is_d & no_bad_characters).fillna(False)

rsc_df = corpus[mask].copy()            # filtered DataFrame

mask = ~rsc_df["doi"].astype(str).str.startswith(("http://", "https://"), na=False)

rsc_df.loc[mask, "doi"] = "https://doi.org/" + rsc_df.loc[mask, "doi"].astype(str)

rsc_df["suffix"] = rsc_df["doi"].str.rsplit("/", n=1).str[-1]
rsc_df.to_csv("RSC_doi_only.csv", index=False)

existing_rsc = pd.read_csv("DOI_RSC_PoP.csv")
# pick the first (or named) column – adjust if your file uses another name
processed_set = (
    existing_rsc.iloc[:, 0]            # first column of the CSV
               .astype(str)
               .str.strip()
               .str.lower()            # ← case‑fold
               .unique()
               .tolist()
)
processed_set = set(processed_set)  # convert to a speedy lookup set
new_mask   = ~rsc_df["suffix"].isin(processed_set)
new_rsc = rsc_df[new_mask].copy()
new_rsc = new_rsc.drop(columns="suffix")
new_rsc.to_csv("New_RSC_Doi_from_Kulik.csv", index=False)