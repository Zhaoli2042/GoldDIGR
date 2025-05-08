import re
import nltk

import glob

import os
# Download necessary NLTK data if not already present
nltk.download('punkt_tab')

# Define the possible regex patterns for footers/page numbers.
# Each pattern looks for the specified keyword optionally followed by whitespace and one or more digits.
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
'''
def is_xyz_line(line):
    """
    Returns True if the line matches the pattern for an xyz coordinate line,
    which we define as an element symbol followed by three floating point numbers.
    """
    # The regex matches a line that starts with an element symbol (one or two letters)
    # followed by three floats (allowing for negative numbers and decimals)
    pattern = r"^\s*[A-Za-z]{1,2}\s+[-+]?\d*\.\d+\s+[-+]?\d*\.\d+\s+[-+]?\d*\.\d+\s*$"
    return re.match(pattern, line) is not None

def has_at_least_three_floats(line):
    """
    Checks if the line contains at least three floats.
    """
    floats = re.findall(r'[-+]?\d*\.\d+', line)
    return len(floats) >= 3

'''
def is_xyz_line(line):
    """
    Returns True if the line qualifies as an xyz coordinate line.
    
    Criteria:
      - The line must contain at least 3 and no more than 3 floats (numbers with a decimal point).
      - The line must contain no more than 30 letters (alphabetic characters).
      - The line must not contain any forbidden symbols: "=", "%", "(", ")", "!", "@", "°".
    """
    # Check for forbidden symbols.
    forbidden_symbols = ["=", "%", "(", ")", "!", "@", "°"]
    if any(symbol in line for symbol in forbidden_symbols):
        return False
    
    floats = re.findall(r'[-+]?\d*\.\d+', line)
    count = len(floats)
    if count < 3 or count > 3:
        return False
    
    # Count letters in the line.
    letters = re.findall(r'[A-Za-z]', line)
    if len(letters) > 4:
        return False

    # If there are exactly 3 floats, ensure there is something else (letter or integer).
    # Check for integers (numbers without a decimal point).
    integers = re.findall(r'(?<!\.)\b\d+\b(?!\.)', line)
    if len(floats) == 3 and not (letters or integers):
        return False

    return True

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

# Energy indicator patterns. If a line contains any of these (case insensitive), remove it.
energy_indicators = ["a.u.", "free energy", "hartree", "scf", "gibbs", "model",
                     "zero point", "chemical potential", "dispersion correction",
                     "imaginary", "frequenc", "cm-1"]

os.makedirs("ts_rm_footer/", exist_ok=True)
txt_files = glob.glob("*.txt")
for filename in txt_files:
    # Skip files that have already been processed
    if filename.endswith(".rm_footer.txt"):
        continue

    # Read the text file converted from PDF
    with open(filename, "r", encoding="utf-8") as file:
        text = file.read()

    # Detect the most probable footer pattern for this file.
    detected_pattern = detect_footer_pattern(text)
    if detected_pattern is None:
        print("No footer pattern detected. Skipping file.")
        continue

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
                print(line)
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
        # Create a new filename by appending '.rm_footer' before the file extension.
        new_filename = filename.replace(".txt", ".rm_footer.txt")
        new_filename = "ts_rm_footer" + '/' + new_filename
        
        # finally, check if the cleaned file contains "TS"
        if not contains_ts_pattern(clean_text): continue
        
        # Write the cleaned text to the new file
        with open(new_filename, "w", encoding="utf-8") as file:
            file.write(clean_text)
    else:
        # if no xyz line found, do not write the file
        print("No xyz block (lines with at least three floats) found.")
    
    print(f"Footer/header lines removed. Clean file saved as: {new_filename}")