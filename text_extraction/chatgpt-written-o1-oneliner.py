import re
import os

import yaml

def count_files_in_folder(folder_path):
    # List and count only files (not directories)
    num = len([f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))])
    print(f"{num} files in {folder_path}")
    return num

def is_coordinate_line(line):
    """
    Returns True if the line appears to be a valid coordinate line, e.g.:
        C   0.123   -4.56   0.789
    We allow an atomic symbol (capital letter + optional lowercase letters),
    followed by at least 3 numeric columns.
    """
    parts = line.split()
    if len(parts) < 4:
        return False
    
    # Check that the first part is an atomic symbol (e.g. "C", "Pd", "Br", etc.).
    if not re.match(r"^[A-Z][a-z]*$", parts[0]):
        return False

    # Next three parts should be numeric (with optional sign, decimals, scientific notation).
    for num_str in parts[1:4]:
        if not re.match(r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$", num_str):
            return False

    return True

def is_header_or_footer(line):
    """
    Returns True if 'line' looks like it's part of a page header/footer
    that should be skipped entirely.

    Examples to skip might include:
      - "Electronic Supplementary Material (ESI) for Chemical Science"
      - "This journal is © The Royal Society of Chemistry 2012"
      - "Page 10", "Footnote #1", or short lines like "S16"
    Adjust the logic/keywords/regex for your specific PDF's header/footer patterns.
    """
    line_stripped = line.strip()

    # 1) Check specific known phrases
    lower = line_stripped.lower()
    if any(phrase in lower for phrase in [
        "electronic supplementary material",
        "this journal is © the royal society",
        "footnote", "supporting information"
    ]):
        return True

    # 2) Simple check for "Page X" patterns
    if re.match(r"^\s*(page|p)\s*\d+$", lower):
        return True

    # 3) Sometimes numeric or short lines like "S16" may be page markers
    #    E.g. "S16", "S17", "S99", etc. Adjust pattern as needed
    if re.match(r"^[Ss]\d+$", line_stripped):
        return True

    # # 4) If line is very short or purely numeric, it might be a page number
    # #    e.g. "16" alone
    # if re.match(r"^\d+$", line_stripped):
    #     return True

    return False

def parse_line_for_coords(line):
    """
    Extracts ALL valid coordinate quadruples from the given line, returning a list of
    tuples: [(atom, x, y, z), ...].
    
    A valid quadruple is matched by:
      [A-Z][a-z]*    (one uppercase letter + optional lowercase, e.g. 'C', 'Na', 'Pd', 'Br')
      followed by 3 floats (which can be decimal or scientific notation).
    
    Example:
      "Some text S16 H 0.35624900 3.50022000 -1.23595700" 
      => [("H", "0.35624900", "3.50022000", "-1.23595700")]
    """
    # Regex for an atomic symbol + 3 floats
    # Explanation:
    #   ([A-Z][a-z]*)        => atom symbol capturing group
    #   \s+                  => one or more whitespace
    #   ([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?) => float with optional sign, decimals, exponent
    #   repeated 3 times
    pattern = re.compile(
        r"([A-Z][a-z]*)\s+"
        r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+"
        r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+"
        r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w\.])"
    )

    matches = pattern.findall(line)
    # Each match is a tuple of strings, e.g. ("H","0.35624900","3.50022000","-1.23595700")
    return matches

def looks_like_heading(line, consider_pure_numeric_headings=False):
    """
    Returns True if 'line' appears to be a *structure heading*.

    Heuristic approach:
      1) If line has 'ts' => definitely a heading.
      2) Else, if line is a single token (<=20 chars):
         - If it is purely numeric => treat as heading only if `consider_pure_numeric_headings=True`
         - If it can be parsed as coordinates, skip (not a heading)
         - Otherwise => heading

    The user can pass `consider_pure_numeric_headings=True` to interpret lines like "20" or "15"
    as valid structure headings, or leave it False to skip them as likely page numbers.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # 1) 'ts' => definitely heading
    if 'ts' in stripped.lower():
        return True

    # 2) Single token (no spaces), up to 20 chars
    tokens = stripped.split()
    if len(tokens) == 1 and len(stripped) <= 20:
        # If it's purely numeric
        if re.match(r"^\d+$", stripped):
            # Only treat as heading if user has asked for it
            return consider_pure_numeric_headings

        # If it parses as coordinates, skip
        if parse_line_for_coords(stripped):
            return False

        # Otherwise => heading
        return True

    return False

def extract_clean_ts_token(line):
    """
    Splits the line, finds the token containing 'ts' (case-insensitive),
    then removes any 'special' characters (anything not alphanumeric, dash, underscore).
    Returns the cleaned token or None if not found.
    """
    parts = line.split()
    for token in parts:
        if "ts" in token.lower():
            # Remove anything that's not: letters, digits, dash, underscore
            cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "", token)
            return cleaned
    return None

def reformat_ts_blocks_single_line(lines, consider_pure_numeric_headings = False):
    """
    1) Iterate through lines.
    2) When we encounter a heading containing 'ts', start a new block.
    3) For each subsequent line:
       - If it's another heading (like "5a" or "6b-ts") or empty => that ends the current block.
       - Otherwise, parse any coordinate groups from that line using parse_line_for_coords.
         Append them to our current block's data.
    4) We only store blocks whose heading contained 'ts'.
    5) Return a list of (heading, single_line_of_all_coords).
    """
    blocks = []
    i = 0
    n = len(lines)

    collecting = False  # Are we inside a "ts" block?
    current_title = None
    current_coords = []

    while i < n:
        line = lines[i].strip()
        
        # 1) Skip headers/footers
        if is_header_or_footer(line):
            i += 1
            continue
        
        if looks_like_heading(line, consider_pure_numeric_headings = consider_pure_numeric_headings):
            # We found a new heading
            # 1) If we were collecting a block, finalize it
            if collecting and current_title and current_coords:
                # Join all coordinates for the existing block
                blocks.append((current_title, " ".join(current_coords)))

            # 2) Check if this heading actually includes 'ts'
            if 'ts' in line.lower():
                # Start a new block
                collecting = True
                current_title = extract_clean_ts_token(line)
                #print(f"line: {lines[i]}, title: {current_title}")
                current_coords = []
            else:
                # It's a heading for a different structure that is not 'ts'
                collecting = False
                current_title = None
                current_coords = []
                
        elif collecting:
            # We're in a "ts" block, so parse out any coordinate groups from this line
            coords_found = parse_line_for_coords(line)
            for (atom, x, y, z) in coords_found:
                current_coords.append(f"{atom} {x} {y} {z}")

        i += 1

    # End of file: if we were still collecting a "ts" block, finalize it
    if collecting and current_title and current_coords:
        blocks.append((current_title, " ".join(current_coords)))

    return blocks
def write_xyz_from_single_line(coord_line, outfile="molecule.xyz"):
    # Split the single line into tokens
    tokens = coord_line.split()
    
    # We'll parse them in chunks of 4: (Atom, X, Y, Z)
    # The number of atoms is the total token count / 4
    num_atoms = len(tokens) // 4
    
    with open(outfile, "w") as f:
        # Write number of atoms
        f.write(f"{num_atoms}\n")
        # Write a comment line (arbitrary)
        f.write("One-liner coordinates\n")
        
        # Loop through each group of 4 tokens
        for i in range(num_atoms):
            atom = tokens[4*i]
            x    = tokens[4*i + 1]
            y    = tokens[4*i + 2]
            z    = tokens[4*i + 3]
            
            # Format them neatly, e.g. left-justify element, align numbers
            f.write(f"{atom:<2s}  {x:>12s}  {y:>12s}  {z:>12s}\n")

def main(path):
    # Load configuration from YAML file
    with open(f"{path}/config.yaml", "r", encoding="utf8") as f:
        config = yaml.safe_load(f)
    
    #folder = "test-Wang-Angew"
    folder = path #config["folder"]
    # Check for exactly one text file in the folder
    text_files = [f for f in os.listdir(folder) if f.lower().endswith('.txt')]
    if len(text_files) != 1:
        print(f"Expected exactly one text file in {folder}, but found {len(text_files)}: {text_files}")
        return

    txt_name = text_files[0]
    #txt_name = config["txt_name"]
    # False for Wang-Angew, True for others
    consider_pure_numeric_headings = config["consider_pure_numeric_headings"]
    
    filename=f"{folder}/{txt_name}"
    for consider_pure_numeric_headings in [True, False]:
        output_dir=f"{folder}/ts_xyz_files_{consider_pure_numeric_headings}/"
        
        os.makedirs(output_dir, exist_ok=True)
        
        with open(f"{filename}", "r", encoding="utf8") as f:
            lines_from_pdf = f.readlines()
        
        # Extract data
        try:
            ts_data = reformat_ts_blocks_single_line(lines_from_pdf, 
                                                     consider_pure_numeric_headings)
            
            # Display results
            for title, single_line in ts_data:
                #print(f"Block Title: {title}")
                #print("All coords on one line:")
                #print(single_line)
                if len(single_line.split()) % 4 != 0:
                    print(f"{title} is not dividable by 4, wrong!")
                else:
                    #print(f"{title} is dividable by 4, good!, # atoms: {len(single_line.split()) / 4}")
                    write_xyz_from_single_line(single_line, 
                                               f"{output_dir}/RESULT-{title}.xyz")
                #print()
        except:
            print(f"CANNOT PROCESS {path}")
        
####################
directory = os.getcwd()
for filename in os.listdir(directory):
    if filename.endswith('.txt'):
        name = os.path.splitext(filename)[0]  # Extract name before .txt
        folder_name = f'test-{name}'          # Create folder name
        folder_path = os.path.join(directory, folder_name)

        # Create the folder if it doesn't exist
        os.makedirs(folder_path, exist_ok=True)
        print(f"Created folder: {folder_path}")
        #os.system(f"cp config.yaml {folder_path}/")
ddir = [d for d in os.listdir("./") if os.path.isdir(os.path.join("./", d)) and d.startswith("test-")]
#dddir = "test-Dang-JACS"
for dddir in ddir:
    print(dddir)
    main(dddir)
    try:
        count_files_in_folder(f"{dddir}/ts_xyz_files_True")
    except:
        "folder not exist"
    try:
        count_files_in_folder(f"{dddir}/ts_xyz_files_False")
    except:
        "folder not exist"