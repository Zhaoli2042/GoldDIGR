import requests
from extract_links import extract_links_from_file, smart_click
from extract_links import _looks_like_download
from pathlib import Path
import time
import pandas as pd

df = pd.read_csv("filtered_SpringerNature_merged_URL_reaction_class.csv")
links = df['ArticleURL']
last_record = 0
#headers = {"User-Agent": "TDMCrawler"} # RSC Requirements
headers = {}
ReadDOI = False
for a in range(0 + last_record, 3):
    text_string = links[a]
    r = requests.get(text_string, 
                     timeout=100, 
                     headers = headers,
                     stream=True)
    
    with open("output.txt", "wb") as f:
        if r.status_code == 200:
            for chunk in r.iter_content(2048):
                f.write(chunk)

    if not ReadDOI: doi = text_string.split('/')[-1].upper()
    else: doi = None

    for link in extract_links_from_file("output.txt", 
                                        base_url = text_string):
        if ReadDOI and "doi.org" in link:
            if doi is not None: continue
            print(link)
            doi = link.split('/')[-1]
            print(doi)
        # Remove strange symbols
        doi = doi.translate(str.maketrans('', '', '&^'))
        if _looks_like_download(link):
            try:
                smart_click(link, save_dir = "./SI/")
            except:
                print(f"{link} cannot be clicked!")
            time.sleep(2)
    if doi is not None:
        Path("output.txt").rename(f"./Paper-Raw/{doi}.txt")
    
    time.sleep(60)
