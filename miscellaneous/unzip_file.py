from pathlib import Path
from zipfile import ZipFile, BadZipFile

def UNZIP_FILE(source_file):

    src_zip = source_file
    
    if not src_zip.is_file():
        raise FileNotFoundError(f"{src_zip} does not exist or is not a file")

    dest_dir =src_zip.parent
    
    extracted_paths: list[Path] = []
    try:
        with ZipFile(src_zip) as zf:
            for member in zf.namelist():
                # Use .extract() instead of .extractall() to gather returned paths
                extracted_path = Path(zf.extract(member, path=dest_dir)).resolve()
                extracted_paths.append(extracted_path)
    except BadZipFile as e:
        raise BadZipFile(f"{src_zip} is not a valid ZIP archive") from e

# ----test----
# ZIP_FILE: Path = Path("anie202016257-sup-0001-pblack.zip").expanduser().resolve()
# UNZIP_FILE(ZIP_FILE)