import requests
from pathlib import Path
import time
import pandas as pd
# Simple GET
df = pd.read_csv("New_RSC_Doi_from_Kulik.csv")

df = df.drop_duplicates(subset='doi', keep='first')

df.to_csv("New_RSC_Doi_from_Kulik_RemoveDuplicate.csv")