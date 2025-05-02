import requests
from extract_links import extract_links_from_file, smart_click
from extract_links import _looks_like_download
from pathlib import Path
import time
import pandas as pd
# Simple GET
# a PDF + CIF
#text_string = "https://pubs.rsc.org/en/content/articlelanding/2025/cy/d5cy00187k"
# 1 PDF + 2 excel
#text_string = "https://pubs.rsc.org/en/content/articlelanding/2025/sc/d5sc01557j"
# 1 PDF + 2 CIF
#text_string = "https://pubs.rsc.org/en/content/articlelanding/2025/sc/d5sc02085a"
# 1 PDF + MP4
#text_string = "https://pubs.rsc.org/en/content/articlelanding/2025/sc/d5sc01663k"

# long url
#text_string = "https://pubs.rsc.org/en/content/articlehtml/2025/cc/d5cc00650c?casa_token=nl4-n9mExngAAAAA:HlB3yybMiQlSoEhXkNfvlrTMXJDkUUhcWCOn4kWKp52vVK74Vyg4UO0V4GyrYt1DdsR-A5WKkwGg5w"

df = pd.read_csv("New_RSC_Doi_from_Kulik.csv")
links = df['doi']
#links = ['https://doi.org/10.1039/b002529l']
for a in range(0, 3000):
    text_string = links[a]
    headers = {"User-Agent": "TDMCrawler"}
    r = requests.get(text_string, 
                     timeout=100, 
                     headers = headers,
                     stream=True)
    
    with open("output.txt", "wb") as f:
        if r.status_code == 200:
            for chunk in r.iter_content(2048):
                f.write(chunk)
    
    doi = None
    for link in extract_links_from_file("output.txt", 
                                        base_url = text_string):
        if "doi.org" in link:
            if doi is not None: continue
            print(link)
            doi = link.split('/')[-1]
        if _looks_like_download(link):
            print(link)
            smart_click(link, save_dir = "./SI/")
    if doi is not None:
        Path("output.txt").rename(f"./Paper-Raw/{doi}.txt")
    
    time.sleep(10)