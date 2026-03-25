#!/bin/bash
# convert_to_bids.sh - Orchestrate the full raw → BIDS pipeline for a single subject.
#
# Usage:
#   ./convert_to_bids.sh <scanner_id> <session_id> <bids_root> <raw_data_root> [csv_path]
#
# Arguments:
#   scanner_id    Scanner pseudonym (e.g. TYCM-RTYX) — looked up in the subject CSV
#   session_id    Session number (e.g. 01 or 02)
#   bids_root     Path to the BIDS dataset root directory
#   raw_data_root Path to the root of raw data (scanner_id/NIFTI will be appended)
#   csv_path      (optional) Path to subject list CSV [default: <script_dir>/NRBR_subject_list.csv]
#
# Example:
#   ./convert_to_bids.sh TYCM-RTYX 01 /data/BIDS /data/raw

set -e

if [ $# -lt 4 ]; then
    echo "Usage: $0 <scanner_id> <session_id> <bids_root> <raw_data_root> [csv_path]"
    echo ""
    echo "Example:"
    echo "  $0 TYCM-RTYX 01 /data/BIDS /data/raw"
    exit 1
fi

SCANNER_ID=$1
SESSION=$2
BIDS_ROOT=$(realpath "$3")
RAW_ROOT=$(realpath "$4")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_PATH="${5:-$SCRIPT_DIR/NRBR_subject_list.csv}"

SOURCE_PATH="$RAW_ROOT/$SCANNER_ID/NIFTI"
MAPPINGS_DIR="$BIDS_ROOT/code/mappings"

# ── Validate inputs ──────────────────────────────────────────────────────────

if [ ! -f "$CSV_PATH" ]; then
    echo "Error: subject list CSV not found: $CSV_PATH"
    echo "Pass the path as the 5th argument or place NRBR_subject_list.csv next to this script."
    exit 1
fi

if [ ! -d "$SOURCE_PATH" ]; then
    echo "Error: Source NIFTI directory not found: $SOURCE_PATH"
    exit 1
fi

# ── Resolve subject ID from CSV ───────────────────────────────────────────────

SUBJECT=$(python3 -c "
import csv, sys
sid = '$SCANNER_ID'
with open('$CSV_PATH', newline='', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        if row.get('Pseudonym', '').strip() == sid:
            print(row['BIDS-ID'].strip().zfill(2))
            sys.exit(0)
sys.exit(1)
" 2>/dev/null) || {
    echo "Error: scanner_id='$SCANNER_ID' not found in $CSV_PATH"
    exit 1
}

SES_LABEL="ses-$(printf '%02d' "$SESSION" 2>/dev/null || echo "$SESSION")"

echo "Resolved: $SCANNER_ID → sub-$SUBJECT $SES_LABEL"
echo ""

MAPPING_FILE="$MAPPINGS_DIR/sub-${SUBJECT}_ses-${SESSION}_mapping.yaml"
LOG_DIR="$BIDS_ROOT/sub-${SUBJECT}/$SES_LABEL"
LOG_FILE="$LOG_DIR/bids_conversion.log"

mkdir -p "$LOG_DIR" "$MAPPINGS_DIR"

# Start logging
exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== BIDS Conversion Log ==="
echo "Date: $(date)"
echo "Scanner ID:  $SCANNER_ID"
echo "Subject:     sub-$SUBJECT"
echo "Session:     $SES_LABEL"
echo "Source:      $SOURCE_PATH"
echo "BIDS root:   $BIDS_ROOT"
echo "==========================="
echo ""

# ── Activate Python environment ───────────────────────────────────────────────

if [ -f ~/python-envs/prf-pipeline/bin/activate ]; then
    source ~/python-envs/prf-pipeline/bin/activate
fi

# ── Step 1: Generate scan mapping ─────────────────────────────────────────────

echo "Step 1: Generating scan mapping..."
python3 "$SCRIPT_DIR/generate_bids_config.py" \
    --mode folders \
    --source "$SOURCE_PATH" \
    --task prf \
    --session "$SESSION" \
    --subject "$SUBJECT" \
    --out-dir "$MAPPINGS_DIR" \
    --no-prompt

echo ""
echo "Mapping written to: $MAPPING_FILE"
echo ""

# ── Step 2: Dry run ───────────────────────────────────────────────────────────

echo "Step 2: Dry run..."
python3 "$SCRIPT_DIR/copy2bids.py" \
    --mode folders \
    --source "$SOURCE_PATH" \
    --dest "$BIDS_ROOT" \
    --config "$MAPPING_FILE" \
    --subject "$SUBJECT" \
    --session "$SESSION" \
    --dry

echo ""
read -p "Proceed with actual conversion? [Y/n]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
    echo "Aborted. No files copied."
    echo "Log saved to: $LOG_FILE"
    exit 0
fi

# ── Step 3: Actual copy ───────────────────────────────────────────────────────

echo "Step 3: Copying files..."
python3 "$SCRIPT_DIR/copy2bids.py" \
    --mode folders \
    --source "$SOURCE_PATH" \
    --dest "$BIDS_ROOT" \
    --config "$MAPPING_FILE" \
    --subject "$SUBJECT" \
    --session "$SESSION" \
    --method link

echo ""
echo "Done! Files linked to: $BIDS_ROOT/sub-$SUBJECT/$SES_LABEL/"
echo "Log saved to:          $LOG_FILE"
echo ""
echo "Next: commit the mapping and review with bids-validator"
echo "  git -C $BIDS_ROOT add code/mappings/sub-${SUBJECT}_ses-${SESSION}_mapping.yaml"
echo "  git -C $BIDS_ROOT commit -m 'Convert sub-$SUBJECT $SES_LABEL ($SCANNER_ID)'"
echo ""
echo "=== End of BIDS Conversion Log ==="
echo "Completed at: $(date)"
