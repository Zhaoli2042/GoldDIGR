# ── SNIPPET: results_backup_verified_aggregation/DFT-singlepoint-OSG-Condor_default ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Invariants:
#   - Only back up files older than MIN_FILE_AGE and not modified within MIN_QUIET_TIME.
#   - Do not delete originals until archive is created AND tar -tzf verification succeeds AND atomic rename completes.
#   - Write a manifest per backup with IN_PROGRESS status to support resume.
#   - Preserve directory structure relative to results/ inside the backup tarball.
# Notes: Destination path logic is environment/site specific; keep placeholders.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: backup_results.sh

CHECK_INTERVAL={{CHECK_INTERVAL}}
MIN_FILE_AGE={{MIN_FILE_AGE}}
MIN_QUIET_TIME={{MIN_QUIET_TIME}}
MIN_FILES_TO_PACK={{MIN_FILES_TO_PACK}}
DISK_ALERT_THRESHOLD=90

RESULTS_DIR="{{RESULTS_DIR}}"
DEST_BASE="{{DEST_BASE}}"
PROJECT_NAME=""

LOG_FILE="backup_results.log"
MANIFEST_DIR=".backup_manifests"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
log_error() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${RED}ERROR:${NC} $1" | tee -a "$LOG_FILE"; }
log_warn() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${YELLOW}WARNING:${NC} $1" | tee -a "$LOG_FILE"; }
log_success() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${GREEN}SUCCESS:${NC} $1" | tee -a "$LOG_FILE"; }

setup_paths() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [ -z "$RESULTS_DIR" ] || [ "$RESULTS_DIR" = "{{RESULTS_DIR}}" ]; then
        if [ -d "$SCRIPT_DIR/results" ]; then
            RESULTS_DIR="$SCRIPT_DIR/results"
        else
            log_error "Cannot find results/ directory."
            exit 1
        fi
    fi

    if [ -z "$PROJECT_NAME" ]; then
        local workflow_parent
        workflow_parent=$(dirname "$SCRIPT_DIR")
        PROJECT_NAME=$(basename "$workflow_parent")

        if [ "$PROJECT_NAME" = "home" ] || [ "$PROJECT_NAME" = "$USER" ]; then
            PROJECT_NAME="dft_energy_results"
        fi
    fi

    DEST_DIR="$DEST_BASE/dft_energy_backups/$PROJECT_NAME"
    mkdir -p "$MANIFEST_DIR"
}

check_disk_usage() {
    if [ ! -d "$DEST_BASE" ]; then
        log_warn "Destination base $DEST_BASE does not exist yet"
        return 0
    fi

    local usage
    usage=$(df "$DEST_BASE" 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')

    if [ -n "$usage" ] && [ "$usage" -ge "$DISK_ALERT_THRESHOLD" ]; then
        log_error "ALERT: Destination storage is ${usage}% full! (threshold: ${DISK_ALERT_THRESHOLD}%)"
        log_error "Location: $DEST_BASE"
        return 1
    elif [ -n "$usage" ]; then
        log "Destination disk usage: ${usage}%"
    fi
    return 0
}

find_eligible_files() {
    local now=$(date +%s)
    local min_age_cutoff=$((now - MIN_FILE_AGE))
    local quiet_cutoff=$((now - MIN_QUIET_TIME))

    find "$RESULTS_DIR" -name "*_results.tar.gz" -type f 2>/dev/null | while read -r file; do
        local mtime
        mtime=$(stat -c %Y "$file" 2>/dev/null)
        [ -z "$mtime" ] && continue
        if [ "$mtime" -lt "$min_age_cutoff" ] && [ "$mtime" -lt "$quiet_cutoff" ]; then
            echo "$file"
        fi
    done
}

create_backup() {
    local file_list="$1"
    local file_count="$2"
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_name="backup_${timestamp}_n${file_count}.tar.gz"
    local backup_tmp="$DEST_DIR/${backup_name}.tmp"
    local backup_final="$DEST_DIR/${backup_name}"
    local manifest_file="$MANIFEST_DIR/manifest_${timestamp}.txt"

    log "Starting backup: $backup_name ($file_count files)"

    if ! mkdir -p "$DEST_DIR" 2>/dev/null; then
        log_error "Cannot create destination directory: $DEST_DIR"
        return 1
    fi

    if ! check_disk_usage; then
        log_error "Aborting backup due to disk space issues"
        return 1
    fi

    echo "# Backup manifest: $backup_name" > "$manifest_file"
    echo "# Created: $(date)" >> "$manifest_file"
    echo "# Status: IN_PROGRESS" >> "$manifest_file"
    echo "# Destination: $backup_final" >> "$manifest_file"
    echo "# Files:" >> "$manifest_file"
    echo "$file_list" >> "$manifest_file"

    log "Creating archive at $backup_tmp..."

    if ! echo "$file_list" | tar -czf "$backup_tmp" -C "$RESULTS_DIR" --files-from=<(
        echo "$file_list" | while IFS= read -r f; do
            echo "${f#$RESULTS_DIR/}"
        done
    ) 2>/dev/null; then
        log_error "Failed to create archive: $backup_tmp"
        echo "# Status: FAILED_CREATE" >> "$manifest_file"
        rm -f "$backup_tmp"
        return 1
    fi

    log "Verifying archive integrity..."
    if ! tar -tzf "$backup_tmp" > /dev/null 2>&1; then
        log_error "Archive verification failed: $backup_tmp"
        echo "# Status: FAILED_VERIFY" >> "$manifest_file"
        rm -f "$backup_tmp"
        return 1
    fi

    local archive_size
    archive_size=$(du -h "$backup_tmp" 2>/dev/null | cut -f1)
    log "Archive verified: $archive_size"

    if ! mv "$backup_tmp" "$backup_final"; then
        log_error "Failed to rename archive"
        echo "# Status: FAILED_RENAME" >> "$manifest_file"
        return 1
    fi

    log_success "Archive created: $backup_final ($archive_size)"

    log "Removing original files..."
    local deleted=0
    local failed=0

    while IFS= read -r file; do
        [ -z "$file" ] && continue
        if rm -f "$file" 2>/dev/null; then
            deleted=$((deleted + 1))
        else
            log_warn "Failed to delete: $file"
            failed=$((failed + 1))
        fi
    done <<< "$file_list"

    log "Deleted $deleted files ($failed failed)"
    find "$RESULTS_DIR" -type d -empty -delete 2>/dev/null || true

    sed -i 's/IN_PROGRESS/COMPLETE/' "$manifest_file"
    echo "# Completed: $(date)" >> "$manifest_file"
    echo "# Deleted: $deleted, Failed: $failed" >> "$manifest_file"

    log_success "Backup complete: $backup_name"
    return 0
}

resume_incomplete() {
    local incomplete
    incomplete=$(grep -l "IN_PROGRESS\|FAILED" "$MANIFEST_DIR"/manifest_*.txt 2>/dev/null || true)
    [ -z "$incomplete" ] && return 0

    log_warn "Found incomplete backup manifest(s), checking..."

    for manifest in $incomplete; do
        local dest=$(grep "^# Destination:" "$manifest" | cut -d' ' -f3)
        local tmp_file="${dest}.tmp"
        local status=$(grep "^# Status:" "$manifest" | tail -1 | cut -d' ' -f3)

        case "$status" in
            IN_PROGRESS)
                if [ -f "$tmp_file" ]; then
                    log "Found incomplete archive: $tmp_file"
                    if tar -tzf "$tmp_file" > /dev/null 2>&1; then
                        log "Archive is valid, completing..."
                        if mv "$tmp_file" "$dest"; then
                            grep -v "^#" "$manifest" | while read -r file; do
                                [ -f "$file" ] && rm -f "$file"
                            done
                            sed -i 's/IN_PROGRESS/COMPLETE/' "$manifest"
                            log_success "Resumed and completed: $dest"
                        fi
                    else
                        log_warn "Archive is corrupt, will retry"
                        rm -f "$tmp_file"
                    fi
                fi
                ;;
            FAILED_*)
                log_warn "Previous backup failed ($status), will retry"
                rm -f "$manifest"
                ;;
        esac
    done
}

run_backup_cycle() {
    log "=============================================="
    log "Starting backup cycle"
    log "Results dir: $RESULTS_DIR"
    log "Destination: $DEST_DIR"
    log "=============================================="

    resume_incomplete

    log "Scanning for files older than $((MIN_FILE_AGE / 3600)) hours..."
    local eligible_files
    eligible_files=$(find_eligible_files)

    if [ -z "$eligible_files" ]; then
        log "No eligible files found"
        return 0
    fi

    local file_count
    file_count=$(echo "$eligible_files" | grep -c .)
    log "Found $file_count eligible files"

    if [ "$file_count" -lt "$MIN_FILES_TO_PACK" ]; then
        log "Waiting for at least $MIN_FILES_TO_PACK files (currently $file_count)"
        return 0
    fi

    create_backup "$eligible_files" "$file_count"
}

main() {
    case "${1:-}" in
        --run-once) setup_paths; run_backup_cycle; exit 0 ;;
        --status) setup_paths; echo "Recent log entries:"; tail -10 "$LOG_FILE" 2>/dev/null || echo "(no log file yet)"; exit 0 ;;
        --help|-h)
            echo "Usage: $0 [--run-once|--status|--help]"
            exit 0
            ;;
        "") ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac

    setup_paths

    log "=============================================="
    log "Backup monitor started"
    log "User: $USER"
    log "Results: $RESULTS_DIR"
    log "Destination: $DEST_DIR"
    log "Check interval: $((CHECK_INTERVAL / 3600)) hours"
    log "Min file age: $((MIN_FILE_AGE / 3600)) hours"
    log "Min files to pack: $MIN_FILES_TO_PACK"
    log "=============================================="

    run_backup_cycle

    while true; do
        sleep "$CHECK_INTERVAL"
        run_backup_cycle
    done
}

main "$@"
