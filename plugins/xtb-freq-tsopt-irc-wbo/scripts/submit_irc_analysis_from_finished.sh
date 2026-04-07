#!/bin/bash
# submit_irc_analysis_from_finished.sh
set -euo pipefail

# ---------------- Configuration ----------------
FINISHED_LIST_FILE="finished.txt"  # one TS path per line
BATCHNAME="AIRC"                            # SLURM job name prefix
JOB_LIMIT=200                             # max concurrent jobs with this tag
CHECK_EVERY=30                             # seconds between queue checks
SUBMIT_TEMPLATE="irc_analysis.submit.template"  # this repo dir

# ---------------- Sanity checks ----------------
if [ ! -f "$FINISHED_LIST_FILE" ]; then
  echo "Error: '$FINISHED_LIST_FILE' not found."
  exit 1
fi
if [ ! -f "$SUBMIT_TEMPLATE" ]; then
  echo "Error: submit template not found at '$SUBMIT_TEMPLATE'."
  exit 1
fi

echo "Starting IRC-analysis submissions from '$FINISHED_LIST_FILE'..."
echo "Throttle: ${JOB_LIMIT} jobs tagged '${BATCHNAME}'."

SCRIPT_DIR=$(pwd)

# ---------------- Build unique parent folder list ----------------
# Each finished.txt line is a TS dir; we want its parent “block” folder.

mapfile -t PARENT_DIRS < <(
  awk '{print $1}' "$FINISHED_LIST_FILE" |
  while IFS= read -r p; do dirname -- "$p"; done | sort -u
)
TOTAL_PARENTS=${#PARENT_DIRS[@]}
echo "Found ${TOTAL_PARENTS} unique parent folders."

# ---------------- Loop over parent dirs ----------------
for ((idx=0; idx< TOTAL_PARENTS; idx++)); do
  PARENT_DIR=${PARENT_DIRS[$idx]}
  [ -z "$PARENT_DIR" ] && continue
  printf '[%d/%d] Processing parent: %s\n' "$((idx+1))" "$TOTAL_PARENTS" "$PARENT_DIR"

  # Determine if any zip here needs IRC_Analysis (skip 'crash' zips)
  needs_job=false
  shopt -s nullglob
  for zip_file in "$PARENT_DIR"/*.zip; do
    [[ "$zip_file" == *crash* ]] && continue
    # Skip if it already has IRC_Analysis/
    if { unzip -l "$zip_file" || true; } | grep -q "IRC_Analysis/"; then
      continue
    fi
    # Submit only if finished_irc.trj exists in the zip (like spin pipeline)
    if { unzip -l "$zip_file" || true; } | grep -q "finished_irc.trj"; then
      echo "  -> Needs IRC analysis: $(basename "$zip_file")"
      needs_job=true
      break
    fi
  done
  shopt -u nullglob

  if [ "$needs_job" != true ]; then
    echo "  -> No zips needing IRC analysis in this parent."
    echo "---"
    continue
  fi

  # Friendly job name components (match your spin submitter style)
  index=$(echo "$PARENT_DIR" | grep -oP '(?:/All-XYZ|/all-pdf-xyz)/\K[^/]+') || true
  [ -z "${index:-}" ] && index="NA"
  block=$(basename "$PARENT_DIR")
  # Remove single quotes (and spaces/colons if needed) to keep sbatch happy
  block="${block//\'/}"
  JOB_NAME="${BATCHNAME}-${index}-${block}"

  # Skip if already queued
  if squeue -u "$USER" --noheader -o "%.200j" | grep -q "${JOB_NAME}$"; then
    echo "  -> Skip: '${JOB_NAME}' already in queue."
    continue
  fi

  # Queue throttling
  while true; do
    current_jobs=$(squeue -u "$USER" -h -o "%j" | grep -F "$BATCHNAME" | wc -l || true)
    if (( current_jobs < JOB_LIMIT )); then
      echo "  --> Submitting job '${JOB_NAME}' for ${PARENT_DIR} (in-queue: ${current_jobs}/${JOB_LIMIT})"
      submit_file="irc_analysis.${index}_${block}.submit"
      template_content=$(<"$SUBMIT_TEMPLATE")
      modified="${template_content//JOBNAME_PLACEHOLDER/$JOB_NAME}"
      modified="${modified//FILEPATH/${PARENT_DIR}}"
      printf '%s\n' "$modified" > "$submit_file"
      (cd "$SCRIPT_DIR" && sbatch "$submit_file")
      break
    else
      printf '[%s] Job limit reached (%d/%d). Sleeping %ds...\n' \
        "$(date '+%H:%M:%S')" "$current_jobs" "$JOB_LIMIT" "$CHECK_EVERY"
      sleep "$CHECK_EVERY"
    fi
  done
done

echo "All parent folders processed."
