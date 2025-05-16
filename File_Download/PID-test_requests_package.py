import requests
from extract_links import extract_links_from_file, smart_click
from extract_links import _looks_like_download
from pathlib import Path
import time
import pandas as pd

import sys, pathlib
import webbrowser

import os, signal, threading
import subprocess, platform, psutil
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

from selenium.common.exceptions import TimeoutException, NoSuchElementException
from urllib3.exceptions import ReadTimeoutError

import pathlib

from selenium.webdriver.common.keys import Keys

# ──► EDIT THESE THREE LINES ONLY ◄──
HTML_DIR = Path.cwd() / "HTML"
HTML_DIR.mkdir(exist_ok=True)

df = pd.read_csv("AAAS_merged_URL_reaction_class.csv")
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
#dwnld_opt.set_preference("browser.helperApps.neverAsk.openFile",  mime_types)

# ② Disable all internal viewers so they don’t steal the download
dwnld_opt.set_preference("browser.download.viewableInternally.enabledTypes", "")

dwnld_opt.set_preference("browser.download.manager.showAlertOnComplete", False)
dwnld_opt.set_preference("browser.download.manager.closeWhenDone", True)
dwnld_opt.set_preference("browser.download.alwaysOpenPanel", False)
dwnld_opt.set_preference("browser.download.manager.useWindow", False)
dwnld_opt.set_preference("browser.download.manager.focusWhenStarting", False)
dwnld_opt.set_preference("dom.disable_beforeunload", True)
dwnld_opt.set_preference("browser.download.manager.quitBehavior", 2)

# (optional) disable the built-in PDF viewer if you also save PDFs
dwnld_opt.set_preference("pdfjs.disabled", True)                # :contentReference[oaicite:1]{index=1}
# ─────────────────────────────────────────────────────────────────────driver = webdriver.Firefox(options=opts)

TIMEOUT     = 20            # seconds before we force-kill
# ── shared state between the two threads ────────────────────────────
done_event  = threading.Event()          # signals success
pid_holder  = {"pid": None}              # filled by worker thread
# ─────────────────────────────────────────────────────────────────────

def kill_process_tree(root_pid: int, grace: float = 2.0):
    """
    Terminate *root_pid* and all children.
    Works on Linux/macOS/WSL and Windows.
    """
    try:
        parent = psutil.Process(root_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return

    # 1️⃣ try graceful SIGTERM / .terminate() first
    children = parent.children(recursive=True)
    for p in children:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    parent.terminate()

    gone, alive = psutil.wait_procs([parent, *children], timeout=grace)

    # 2️⃣ force-kill anything that ignored terminate()
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass

    # extra belt-and-suspenders for Windows if something survived
    if alive and platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/PID", str(root_pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

def watchdog():
    if done_event.wait(TIMEOUT):
        return                       # download finished in time
    pid = pid_holder["gecko"]
    if pid:
        print(f"✗ download exceeded {TIMEOUT}s → killing tree rooted at {pid}")
        kill_process_tree(pid)

def download_worker(dwnld_opt, DOWNLOAD_DIR):
    start = time.time()
    try:
        dwnld_opt.set_preference("browser.download.dir", 
                                 str(DOWNLOAD_DIR))
        dwnld_opt.page_load_strategy = "eager"
        dwnld_opt.add_argument("--headless")  
        new_driver = webdriver.Firefox(options = dwnld_opt)
        pid_holder["gecko"]   = new_driver.service.process.pid
        pid_holder["firefox"] = new_driver.capabilities.get("moz:processID")  # FYI
        new_driver.set_page_load_timeout(15)   # 15-second cap
        new_driver.get(link)
        
        new_driver.quit()
    except TimeoutException:
        print("DONEEE!!!!")
    except:
        with open("errors.log", "a", encoding="utf-8") as log:
            log.write(f"CANNOT PROCESS LINK {link} for paper {a}, {links[a]}\n")
            new_driver.quit()
    finally:
        try:
            new_driver.quit()
        except:
            pass
    end = time.time()
    print(f"TOOK {end-start} secs\n")

for a in range(309, 1000):
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
            if _looks_like_download(link) and "RecruitmentKit" not in link:
                pid_holder  = {"pid": None}              # filled by worker thread
                #driver.get(link)
                print(link)
                DOWNLOAD_DIR = Path.cwd() / "downloads" / str(a)
                DOWNLOAD_DIR.mkdir(exist_ok=True)
                # ── run the two threads ─────────────────────────────────────────────
                t_worker   = threading.Thread(target=download_worker, 
                                              args=(dwnld_opt, 
                                                    DOWNLOAD_DIR), daemon=True)
                t_watchdog = threading.Thread(target=watchdog, 
                                              daemon=True)
                t_worker.start()
                t_watchdog.start()
                
                t_worker.join()
                t_watchdog.join()
                # try:
                #     new_driver.quit()
                # finally:
                #     pass
                # try:
                #     os.kill(pid_holder['pid'], 9)
                # except:
                #     pass
                time.sleep(2)
    except ReadTimeoutError:
        print(f"{links[a]} time out")
        driver.quit()
    finally:
        print("DPONE")
        driver.quit()
        time.sleep(12)
