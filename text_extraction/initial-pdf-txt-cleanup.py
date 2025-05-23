import re
import nltk

import glob

import os
# Download necessary NLTK data if not already present
#nltk.download('punkt_tab')

# Define the possible regex patterns for footers/page numbers.
# Each pattern looks for the specified keyword optionally followed by whitespace and one or more digits.

homedir=os.getcwd()

patterns = {
    "Page": r'Page\s*\d+',
    "page": r'page\s*\d+',
    "SI-": r'SI-\s*\d+',
    "SI": r'SI\s*\d+',
    "si-": r'si-\s*\d+',
    "si": r'si\s*\d+',
    "S-": r'S-\s*\d+',
    "S": r'S\s*\d+',
    "s-": r's-\s*\d+',
    "s": r's\s*\d+'
}

# --- Footer Pattern Detection ---
# Process a sample text or the full text to count occurrences for each footer pattern.
def detect_footer_pattern(text):
    """
    Detects the most probable footer pattern in the given text using the predefined patterns.
    If overlapping patterns occur, longer keys take precedence.

    Parameters:
        text (str): The text content to analyze.

    Returns:
        str: The most probable footer pattern (the key from footer_patterns).
    """
    sentences = nltk.sent_tokenize(text)
    pattern_occurrences = {}
    for key in patterns.keys():
        combined_pattern = r'\b' + re.escape(key) + r'[\s]*\d+\b'
        occurrences = []
        for sentence in sentences:
            tokens = nltk.regexp_tokenize(sentence, combined_pattern)
            if tokens:
                occurrences.extend(tokens)
        if occurrences:
            pattern_occurrences[key] = occurrences

    if pattern_occurrences:
        # Sort by occurrence count first, then by length of key (longer keys are more specific)
        most_probable = max(pattern_occurrences.items(), key=lambda item: (len(item[1]), len(item[0])))
        return most_probable[0]
    else:
        return None

# ── Helper: split a line by whichever delimiter yields the most tokens ──
def _smart_split(raw: str):
    """
    Return a list of tokens obtained with the “dominant” delimiter.

    Candidates: comma, semicolon, tab, pipe.
    The delimiter that produces the most fields wins.
    If none of those add more fields than plain-whitespace splitting,
    fall back to whitespace splitting.
    """
    raw = raw.rstrip("\n\r")
    # Start with whitespace split as the default
    best_parts = raw.split()
    best_count = len(best_parts)

    for sep in [",", ";", "\t", "|"]:
        if sep in raw:
            parts = [field.strip() for field in raw.split(sep)]
            if len(parts) > best_count:
                best_parts, best_count = parts, len(parts)

    # Remove empty strings that can appear with consecutive delimiters
    return [p for p in best_parts if p]

import periodictable as pt   # pip install periodictable

# Pre-compute a fast-lookup set of valid element symbols (H, He, Li, …)
VALID_SYMBOLS = {el.symbol for el in pt.elements if el.number > 0}

# Simple helper: does a token look like a float with ≥ 2 digits after the dot?
def _is_xyz_float(tok: str) -> bool:
    if tok.count('.') != 1:                     # must contain exactly one '.'
        return False
    whole, frac = tok.lstrip('+-').split('.', 1)
    return frac.isdigit() and len(frac) >= 2 and (whole.isdigit() or whole == '')

def is_xyz_line(line: str) -> bool:
    """
    Return True if *line* looks like a valid XYZ-coordinate entry.
    
    Rules (all must pass):
    1. No forbidden symbols (= % ( ) ! @ °).
    2. Exactly three floats appear in the line, each with ≥ 2 decimal digits.
    3. Those three floats are the **last three tokens**; nothing follows them.
    4. ≤ 4 alphabetic characters total in the line.
    5. The first token that contains letters starts with a valid element symbol.
    """
    # --- NEW EN-DASH HANDLING ---------------------------------------------
    # Treat the Unicode en-dash (U+2013) exactly like ASCII minus.
    line = line.replace("–", "-")
    # -----------------------------------------------------------------------
    
    # 0. Reject any other non-ASCII characters
    if any(ord(ch) > 127 for ch in line):
        return False
    
    # 1. Forbidden symbols
    if any(sym in line for sym in ("=", "%", "(", ")", "!", "@", "°")):
        return False

    # not if you are interested in POSCAR format (VASP related)
    # POSCAR will have only three floats
    #tokens = line.strip().split()
    tokens = _smart_split(line)
    if len(tokens) < 4:                         # need at least: element + 3 coords
        return False

    # ------------------------------------------------------------
    # 2–3.  The final three tokens must be valid XYZ coordinates.
    #       Treat bare 0 (+0 / -0) as “0.0000” or a tiny float 
    #       so it counts as a
    #       proper float with ≥ 2 fractional digits.
    #       using a tiny float instead of adding trailing zeros 
    #       will pass _is_xyz_float() check
    # ------------------------------------------------------------
    for i in range(-3, 0):                              # last three indices
        tok = tokens[i]
        if tok in {"0", "+0", "-0"}:
            sign = tok[0] if tok[0] in "+-" else ""
            tokens[i] = f"{sign}0.0000000001"             # e.g. -0 → -0.0000

    # Re-assemble the corrected line and make this the working string
    line = " ".join(tokens)
    tokens = line.strip().split() # alias for clarity

    # each of the rewritten tail tokens must look like an XYZ float
    if not all(_is_xyz_float(t) for t in tokens[-3:]):
        return False
    
    # Count ALL floats in the line with a permissive regex (sign? digits? . digits+)
    float_strings = re.findall(r'[-+]?\d*\.\d+', line)
    # Must be exactly the same three floats we just validated
    if len(float_strings) != 3:
        return False

    # 4. Total letters guard (matches earlier behaviour)
    if len(re.findall(r'[A-Za-z]', line)) > 4:
        return False

    # # 5. Validate element label (no regex)
    # for tok in tokens:
    #     if not any(ch.isalpha() for ch in tok):
    #         continue
    #     # take the leading consecutive letters (e.g. 'Pd' in 'Pd1')
    #     letters = []
    #     for ch in tok:
    #         if ch.isalpha():
    #             letters.append(ch)
    #         else:
    #             break
    #     symbol = ''.join(letters).capitalize()
    #     if symbol not in VALID_SYMBOLS:
    #         return False
    #     break
    # else:
    #     return False  # no token with letters at all

    return True

# if a file has no "xyz line", this will find some indicators
from collections import OrderedDict
def contains_xyz_indicators(text: str):
    """
    Heuristic scan for tell-tale keywords that hint at Cartesian
    coordinates or XYZ blocks—even when no single line passes the
    strict `is_xyz_line()` test.

    Parameters
    ----------
    text : str
        The entire text content of a file.

    Returns
    -------
    tuple[bool, list[str]]
        (any_found, indicators_found)

        * any_found         – True if ≥ 1 indicator is present.
        * indicators_found  – List of human-readable indicator names
                              (e.g. ['coordinate', 'X Y Z']).

    Indicators searched (case-insensitive)
    --------------------------------------
    1. 'coordinate'          – exact word
    2. 'XYZ'                 – the acronym
    3. 'X Y Z'               – the letters X, Y, Z separated by spaces or tabs
    4. 'geometry'            – singular
    5. 'geometries'          – plural
    """
    patterns = OrderedDict([
        ('coordinate',   r'\bcoordinate\b'),
        ('XYZ',          r'\bxyz\b'),
        ('X Y Z',        r'\bx[ \t]+y[ \t]+z\b'),
        ('geometry',     r'\bgeometry\b'),
        ('geometries',   r'\bgeometries\b'),
    ])

    found = []

    for name, pat in patterns.items():
        if re.search(pat, text, re.IGNORECASE):
            found.append(name)

    return bool(found), found

def is_header_or_footer(line, footer_pattern):
    """
    Returns True if 'line' looks like it's part of a page header/footer
    that should be skipped entirely.

    Parameters:
        line (str): The line of text to check.
        footer_pattern (str): A regex string representing the base footer/page number
                              pattern (e.g., "Page", "S-", etc.). This function will
                              check for this pattern immediately followed by optional whitespace
                              and a number.
    """
    line_stripped = line.strip()
    lower = line_stripped.lower()
    
    # Check for common header/footer phrases.
    if any(phrase in lower for phrase in [
        "electronic supplementary material",
        "this journal is © the royal society",
        "footnote",
        "supporting information"
    ]):
        return True
    
    # Check for basic page numbering patterns.
    if re.match(r"^\s*(page|p)\s*\d+$", lower):
        return True
    if re.match(r"^[Ss]\d+$", line_stripped):
        return True

    # Build a strict regex: line must start with the footer pattern, then optional whitespace,
    # then an integer (only digits, no decimal point), and then nothing else.
    combined_pattern = r'^\s*' + re.escape(footer_pattern) + r'\s*(\d+)\s*$'
    if re.match(combined_pattern, lower):
        return True

    return False
'''
def remove_blank_lines_between_xyz(lines):
    """
    Removes blank lines that are surrounded by two xyz coordinate lines.
    
    Parameters:
        lines (list of str): The list of lines to process.
    
    Returns:
        list of str: The processed list with unnecessary blank lines removed.
    """
    final_lines = []
    num_lines = len(lines)
    for i, line in enumerate(lines):
        # Check if the line is blank and is surrounded by two xyz coordinate lines.
        if line.strip() == "" and i > 0 and i < num_lines - 1:
            if is_xyz_line(lines[i - 1]) and is_xyz_line(lines[i + 1]):
                continue  # Skip this blank line.
        final_lines.append(line)
    return final_lines
'''
def remove_blank_lines_between_xyz(lines):
    """
    Removes contiguous blank lines that are surrounded by two xyz coordinate lines.
    
    Parameters:
        lines (list of str): The list of lines to process.
    
    Returns:
        list of str: The processed list with unnecessary blank lines removed.
    """
    final_lines = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "":
            # Start of a block of blank lines.
            start = i
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            end = i  # First non-blank line after the block (or end of list)
            
            # Check if the blank block is between two xyz coordinate lines.
            if start > 0 and i < len(lines) and is_xyz_line(lines[start - 1]) and is_xyz_line(lines[i]):
                # Skip the entire block.
                continue
            else:
                # Otherwise, keep the blank lines.
                final_lines.extend(lines[start:end])
        else:
            final_lines.append(lines[i])
            i += 1
    return final_lines

def contains_large_float(line, threshold=100):
    """
    Checks if the line contains any float (numbers with a decimal point) 
    with an absolute value greater than threshold. Integers are ignored.
    
    Parameters:
        line (str): The line of text to check.
        threshold (float): The numerical threshold. Defaults to 100.
    
    Returns:
        bool: True if any float in the line has an absolute value greater than threshold.
    """
    # Regex matches floats: numbers that include a decimal point.
    floats = re.findall(r'[-+]?\d*\.\d+', line)
    for num_str in floats:
        try:
            num = float(num_str)
            if abs(num) > threshold:
                return True
        except ValueError:
            continue
    return False
'''
def contains_ts_pattern(text):
    """
    Checks if the text contains the pattern 'TS' in any capitalization variant,
    e.g., "TS", "ts", "Ts", etc.
    
    Parameters:
        text (str): The full text content.
    
    Returns:
        bool: True if any occurrence of the pattern is found, False otherwise.
    """
    # \b ensures we match "TS" as a separate word.
    pattern = r'\bts\b'
    return bool(re.search(pattern, text, re.IGNORECASE))
'''
def contains_ts_pattern(text):
    """
    Checks if the text contains indicators of a Transition State:
    - "TS" in any capitalization (e.g., "TS", "ts", etc.)
    - "transition"
    - "transition state"
    
    Parameters:
        text (str): The full text content.
    
    Returns:
        bool: True if a TS-related term is found, False otherwise.
    """
    # Match "TS" as a whole word, or any phrase with "transition" or "transition state"
    pattern = r'\bts\b|\btransition\b|\b‡\b|'
        
    return bool(re.search(pattern, text, re.IGNORECASE))

# Energy indicator patterns. If a line contains any of these (case insensitive), remove it.
energy_indicators = ["a.u.", "free energy", "hartree", "scf", "gibbs", "model",
                     "zero point", "chemical potential", "dispersion correction",
                     "imaginary", "frequenc", "cm-1"]

def initial_cleanup(filename):
    real_filename = filename.split(os.sep)[-1]
    # Skip files that have already been processed
    if filename.endswith(".rm_footer.txt"):
        return

    # Read the text file converted from PDF
    with open(filename, "r", encoding="utf-8") as file:
        text = file.read()

    # Detect the most probable footer pattern for this file.
    detected_pattern = detect_footer_pattern(text)
    if detected_pattern is None:
        print("No footer pattern detected. Skipping file.")
        with open(homedir + "/" + "PDF-No-Footer.txt", "a", encoding="utf-8") as file:
            file.write(f"{filename}\n")
        return

    print(f"Detected footer pattern: '{detected_pattern}'")

    # --- Removal phase ---
    # Process the text line by line, removing header/footer lines
    clean_lines = []
    for line in text.splitlines():
        # Remove header/footer lines.
        found = False
        for pat in patterns.keys():
            #print(pat)
            if is_header_or_footer(line, pat):
                found = True
                #print(line)
        if found:
            continue
            
        # Remove lines containing energy indicator patterns.
        '''
        lower_line = line.lower()
        if any(ind in lower_line for ind in energy_indicators):
            continue
        
        # Remove lines that contain any float with absolute value greater than 100.
        if contains_large_float(line, threshold=100):
            continue
        '''
        clean_lines.append(line)
    
    # --- Blank Line Removal between Coordinate Lines ---
    final_lines = remove_blank_lines_between_xyz(clean_lines)
    
    # --- Restrict to the xyz Block with Buffer ---
    # Find indices of lines that have at least three floats.
    xyz_indices = [i for i, line in enumerate(final_lines) if is_xyz_line(line)]
    if xyz_indices:
        first_index = xyz_indices[0]
        last_index = xyz_indices[-1]
        # Add a buffer of 20 lines before and after the xyz block.
        start_index = max(0, first_index - 20)
        end_index = min(len(final_lines), last_index + 1)
        final_lines = final_lines[start_index:end_index]
        clean_text = "\n".join(final_lines)
        
        # finally, check if the cleaned file contains "TS"
        # if not found, add "ts_not_found" to filename
        replacement = ".rm_footer.txt"
        if not contains_ts_pattern(clean_text):
            replacement = ".ts_notfound" + "rm_footer.txt"
            with open(homedir + "/" + "PDF-No-TS.txt", "a", encoding="utf-8") as file:
                file.write(f"{filename}\n")
        # Create a new filename by appending '.rm_footer' before the file extension.
        new_filename = real_filename.replace(".txt", replacement)
        new_filename = destination_folder + '/' + new_filename
            
        # Write the cleaned text to the new file
        with open(new_filename, "w", encoding="utf-8") as file:
            file.write(clean_text)
        print(f"Footer/header lines removed. Clean file saved as: {new_filename}")
    else:
        has_coords, markers = contains_xyz_indicators("\n".join(final_lines))
        if has_coords:
            with open(homedir + "/" + "PDF-Potential-xyz.txt", "a", encoding="utf-8") as file:
                file.write(f"{filename} , indicators: {", ".join(markers)}\n")
        # if no xyz line found, do not write the file
        print("No xyz block (lines with at least three floats) found.")
        with open(homedir + "/" + "PDF-No-xyz.txt", "a", encoding="utf-8") as file:
            file.write(f"{filename}\n")

import random

def deterministic_sample(population, k, seed=42):
    state = random.getstate()     # save current RNG state (offset)
    random.seed(seed)             # reset RNG to the chosen seed
    out = random.sample(population, k)
    random.setstate(state)        # restore original RNG state
    return out

# 10 distinct random integers between 0 (inclusive) and 99 (inclusive)
#numbers = deterministic_sample(range(0, 10000), k=20, seed = 20)

First_time = False
if First_time: # from scratch
    for a in range(0, 6500): #numbers:
        print(f"Processing {a} folder")
        departure_folder = f'downloads/{a}/Converted-PDF-To-TXT/'
        destination_folder = f'downloads/{a}/Converted-PDF-To-TXT/'
        if not os.path.isdir(departure_folder): continue
    
        os.makedirs(destination_folder, exist_ok=True)
        txt_files = glob.glob(departure_folder + '/' + "*.txt")
        txt_files = [os.path.normpath(i) for i in txt_files]
        for filename in txt_files:
            if "rm_footer" in filename: continue
            initial_cleanup(filename)
            
else: # continue from an existing list of files
    from pathlib import Path
    with open("2nd_PDF-No-xyz.txt", "r", encoding="utf-8") as f:
        cont_txt_files = [line.rstrip("\n") for line in f]
    for filename in cont_txt_files:
        if "rm_footer" in filename: continue
        destination_folder = str(Path(filename).parent) + '/'
        initial_cleanup(filename)