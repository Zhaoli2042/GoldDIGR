import os
import glob
import docx2txt      # lightweight, pure-Python DOCX extractor

def DOCX_TO_TXT(source_file):   
    without_ext = source_file.with_suffix("")          # PosixPath('XXX/XXX')
    destination_file = without_ext.with_suffix(".txt")
    print(f"DESTINATION: {destination_file}", flush = True)
    txt = docx2txt.process(source_file)          # extract plain text
    with open(destination_file, "w", encoding="utf-8") as f:
        f.write(txt)