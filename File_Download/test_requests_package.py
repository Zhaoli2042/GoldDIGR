import requests
from extract_links import extract_links_from_file, smart_click
from extract_links import _looks_like_download
from pathlib import Path
import time
import pandas as pd

df = pd.read_csv("merged_URL_reaction_class_RSC.csv")
links = df['ArticleURL']
last_record = 0
headers = {"User-Agent": "TDMCrawler"} # Required by RSC

ReadDOI = True

for a in range(START + last_record, END):
    text_string = links[a]

    try:
        r = requests.get(text_string, 
                         timeout=200, 
                         headers = headers,
                         stream=True)
    except:
        print(f"{text_string} cannot be processed")
        continue

    with open("output.txt", "wb") as f:
        if r.status_code == 200:
            for chunk in r.iter_content(2048):
                f.write(chunk)

    if not ReadDOI: doi = text_string.split('/')[-1].upper()
    else: doi = None
    # Get all links
    paper_links = extract_links_from_file("output.txt", base_url = text_string)
    # find doi first
    for link in paper_links:
        if ReadDOI and "doi.org" in link:
            if doi is not None: continue
            print(link)
            doi = link.split('/')[-1]

    if doi is None:
        doi = f"RSC-PAPER-{a}"
    Path(f"./DOI/{doi}/").mkdir(parents=True, exist_ok=True)
    Path("output.txt").rename(f"./DOI/{doi}/Paper-Raw.txt")
    # download the paper
    for link in paper_links:
        if _looks_like_download(link):
            print(link)
            try:
                smart_click(link, save_dir = f"./DOI/{doi}/")
            except:
                print(f"Cannot Process {link} for {doi}")
            time.sleep(2)

    time.sleep(30)
