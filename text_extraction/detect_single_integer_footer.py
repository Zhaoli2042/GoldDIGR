import re

def is_xyz_line(line):
    # For testing, let's assume an xyz line must contain exactly 3 floats and some text.
    floats = re.findall(r'[-+]?\d*\.\d+', line)
    return len(floats) == 3 and bool(re.search(r'[A-Za-z]', line))

def detect_integer_footer(lines, is_xyz_line_func):
    """
    Scans the list of lines for those that contain only a positive integer
    and that are part of an xyz block (i.e. the line immediately before and after
    are valid xyz lines). It returns details about the integer footer if the following
    conditions hold:
      - The integer values (from candidate lines) form a strictly increasing sequence,
        each number exactly one more than the previous.
      - The spacing (line number differences) between consecutive candidate lines is 
        approximately constant, i.e. the difference from the average spacing is at most 1.
    
    Parameters:
        lines (list of str): The file content as a list of lines.
        is_xyz_line_func (function): A function that accepts a line (str) and returns
                                     True if it qualifies as an xyz coordinate line.
    
    Returns:
        dict: A dictionary with keys:
              - "is_integer_footer": True if conditions hold, False otherwise.
              - "line_indices": List of line indices (0-based) of the candidate integer lines.
              - "integers": List of the integer values found.
              - "spacing": List of differences between consecutive candidate line indices.
    """
    candidate_indices = []
    candidate_numbers = []
    
    # Only consider lines that consist solely of a positive integer
    # AND are "in an xyz block": the previous and next line exist and pass is_xyz_line_func.
    for idx, line in enumerate(lines):
        if re.match(r'^\s*\d+\s*$', line):
            if idx > 0 and idx < len(lines) - 1:
                if is_xyz_line(lines[idx - 1]) and is_xyz_line(lines[idx + 1]):
                    candidate_indices.append(idx)
                    candidate_numbers.append(int(line.strip()))
    
    result = {
        "is_integer_footer": False,
        "line_indices": candidate_indices,
        "integers": candidate_numbers,
        "spacing": []
    }
    
    # Need at least two candidates to establish a sequence.
    if len(candidate_numbers) < 2:
        return result

    # Check if the integers form a strictly increasing sequence (difference of exactly 1).
    for i in range(len(candidate_numbers) - 1):
        if candidate_numbers[i+1] - candidate_numbers[i] != 1:
            return result  # Sequence fails the condition.
    
    # Calculate spacing differences between consecutive candidate line indices.
    spacing = []
    for i in range(len(candidate_indices) - 1):
        spacing.append(candidate_indices[i+1] - candidate_indices[i])
    result["spacing"] = spacing
    
    # Compute average spacing.
    avg_spacing = sum(spacing) / len(spacing)
    # Allow a difference of at most 1 from the average spacing.
    if all(abs(diff - avg_spacing) <= 1 for diff in spacing):
        result["is_integer_footer"] = True
    
    return result

# Example usage:
if __name__ == "__main__":
    # Dummy is_xyz_line function for testing purposes.
    
    filename = "ja3c03840_si_001.rm_footer.txt"
    with open(filename, "r", encoding="utf-8") as file:
        sample_text = file.read()
    lines = sample_text.strip().splitlines()
    
    footer_info = detect_integer_footer(lines, is_xyz_line)
    if footer_info["is_integer_footer"]:
        print("Integer footer detected:")
        print("Line indices:", footer_info["line_indices"])
        print("Integer values:", footer_info["integers"])
        print("Spacing between lines:", footer_info["spacing"])
    else:
        print("No valid integer footer detected.")
