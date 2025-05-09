import requests
from extract_links import extract_links_from_file, smart_click
from extract_links import _looks_like_download
from pathlib import Path
import time
import pandas as pd

import sys, pathlib
import webbrowser

#from timeout_functions import run_with_timeout
#df = pd.read_csv("filtered_SpringerNature_merged_URL_reaction_class.csv")
#links = df['ArticleURL']
last_record = 0
#headers = {"User-Agent": "TDMCrawler"} # RSC Requirements
#links = ['https://api.wiley.com/onlinelibrary/tdm/v1/articles/0.1002/anie.201300056']
links = ['https://onlinelibrary.wiley.com/doi/10.1002/anie.201300056']
headers = {
  'Accept': 'text/html',
  'User-agent': 'Mozilla/5.0'
}

"""
Automate a browser to click a link and save the resulting HTML.
Requires: selenium ≥ 4.19, webdriver-manager ≥ 4.0, Firefox + geckodriver.
Install once with:
    pip install selenium webdriver-manager
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

from selenium.common.exceptions import TimeoutException

import pathlib

# ──► EDIT THESE THREE LINES ONLY ◄──
START_URL   = "https://chemistry-europe.onlinelibrary.wiley.com/doi/abs/10.1002/cctc.202500034"     # page that contains the link
HTML_DIR = Path.cwd() / "HTML"
HTML_DIR.mkdir(exist_ok=True)

df = pd.read_csv("Wiley_merged_URL_reaction_class.csv")
links = df['ArticleURL']
# 1. Launch a **real** (headless) Firefox browser
opts = Options()
opts.add_argument("--headless")         # omit this line if you want the window visible
# ────────────────────────────────────

# ── download-related prefs ───────────────────────────────────────────
DOWNLOAD_DIR = Path.cwd() / "downloads"          # absolute path is safest
DOWNLOAD_DIR.mkdir(exist_ok=True)
dwnld_opt = Options()
#dwnld_opt.add_argument("--headless")
dwnld_opt.set_preference("browser.download.folderList",        2)                 # 0-desktop,1-Downloads,2-custom
dwnld_opt.set_preference("browser.download.dir",               str(DOWNLOAD_DIR))
dwnld_opt.set_preference("browser.download.useDownloadDir",    True)
dwnld_opt.set_preference("browser.download.manager.showWhenStarting", False)

# ① Tell Firefox which MIME types to save silently
#    For plain pages add both HTML flavours; add others as needed.
mime_types = ",".join([
    "text/html",
    "application/xhtml+xml",
    "application/octet-stream"               # catch-all fallback
])
dwnld_opt.set_preference("browser.helperApps.neverAsk.saveToDisk", mime_types)
dwnld_opt.set_preference("browser.helperApps.neverAsk.openFile",  mime_types)

# ② Disable all internal viewers so they don’t steal the download
dwnld_opt.set_preference("browser.download.viewableInternally.enabledTypes", "")

# (optional) disable the built-in PDF viewer if you also save PDFs
dwnld_opt.set_preference("pdfjs.disabled", True)                # :contentReference[oaicite:1]{index=1}
# ─────────────────────────────────────────────────────────────────────driver = webdriver.Firefox(options=opts)


for a in range(2, 10):
    OUTPUT_FILE = f"{HTML_DIR}/{a}.html"        # where to save the HTML
    try:
        driver = webdriver.Firefox(
            #executable_path=GeckoDriverManager().install(),
            options=opts,
        )
        # 2. Open the starting page
        driver.get(links[a])
    
        # 3. Click the desired link when it becomes clickable
        #WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.LINK_TEXT, LINK_TEXT))).click()
    
        # 4. Wait until the new page has finished loading
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    
        # 5. Grab the browser’s DOM snapshot (fully rendered HTML)
        html = driver.page_source
    
        # 6. Save it to disk
        pathlib.Path(OUTPUT_FILE).write_text(html, encoding="utf-8")
        print(f"Saved HTML to {OUTPUT_FILE}")
        
        page_links = extract_links_from_file(f"{OUTPUT_FILE}", 
                                             base_url = links[0])
        
        driver.quit()
        for link in page_links:
            if _looks_like_download(link):
                #driver.get(link)
                print(link)
                try:
                    new_driver = webdriver.Firefox(options = dwnld_opt)
                    new_driver.set_page_load_timeout(5)   # 15-second cap
                    #run_with_timeout(new_driver.get(link), .5)
                    new_driver.get(link)
                # WebDriverWait(new_driver, 5).until(
                #     lambda d: d.execute_script("return document.readyState") == "complete"
                # )
                except TimeoutException:
                    print("DONEEE!!!!")
                finally:
                    #print("GOOD!")
                    new_driver.quit()
                time.sleep(2)
    finally:
        print("DPONE")
        time.sleep(10)