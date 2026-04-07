# ── SNIPPET: recursive_tree_walk_bash/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      make_tree.sh
# Invariants:
#   - The loop variable must be local inside the recursive function to avoid being overwritten by recursion.
#   - Enable dotglob/nullglob so hidden files are included and empty globs don't expand to literal patterns.
# Notes: Run `bash make_tree.sh {{TARGET_DIR}}` (defaults to `.`).
# ────────────────────────────────────────────────────────────

#!/bin/bash

# Define the output file and the target directory (defaults to current directory '.')
OUTPUT_FILE="folder_tree.txt"
TARGET_DIR="${1:-.}"

# Initialize the output file with the root folder name
echo "$TARGET_DIR" > "$OUTPUT_FILE"

# Enable options to include hidden files (dotglob) and handle empty directories (nullglob)
shopt -s dotglob nullglob

# Recursive function to build the tree
generate_tree() {
    local current_dir="$1"
    local prefix="$2"
    
    # Put all files and directories into an array
    local items=("$current_dir"/*)
    local count=${#items[@]}
    
    local i # CRITICAL FIX: Make the loop variable local so recursion doesn't overwrite it
    for ((i=0; i<count; i++)); do
        local item="${items[$i]}"
        local basename="${item##*/}"
        
        # Check if this is the last item to format the branch correctly
        if [ $((i + 1)) -eq "$count" ]; then
            echo "${prefix}└── $basename" >> "$OUTPUT_FILE"
            local next_prefix="${prefix}    "
        else
            echo "${prefix}├── $basename" >> "$OUTPUT_FILE"
            local next_prefix="${prefix}│   "
        fi
        
        # If the item is a directory, recurse into it
        if [ -d "$item" ]; then
            generate_tree "$item" "$next_prefix"
        fi
    done
}

echo "Scanning '$TARGET_DIR'..."
generate_tree "$TARGET_DIR" ""
echo "Done! The tree has been saved to $OUTPUT_FILE."
