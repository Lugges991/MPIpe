#!/bin/bash
# convert_to_bids.sh - Orchestrate the full raw → BIDS pipeline.
#
# Usage:
#   ./convert_to_bids.sh <scanner_id> <session_id> <bids_root> <raw_data_root>
#
# Arguments:
#   scanner_id    Scanner pseudonym (e.g. TYCM-RTYX) — looked up in sessions_map.tsv
#   session_id    Session number (e.g. 01 or 02)
#   bids_root     Path to the BIDS dataset root directory
#   raw_data_root Path to the root of raw data (scanner_id/NIFTI will be appended)
#
# Example:
#   ./convert_to_bids.sh TYCM-RTYX 01 /data/BIDS /data/raw
#
# Prerequisites:
#   - Subject already registered:  python register_subject.py ...
#   - sessions_map.tsv exists at:  <bids_root>/code/sessions_map.tsv

set -e

if [ $# -ne 4 ]; then
    echo "Usage: $0 <scanner_id> <session_id> <bids_root> <raw_data_root>"
    echo ""
    echo "Example:"
    echo "  $0 TYCM-RTYX 01 /data/BIDS /data/raw"
    exit 1
fi

SCANNER_ID=$1
SESSION=$2
BIDS_ROOT=$(realpath "$3")
RAW_ROOT=$(realpath "$4")

SESSIONS_MAP="$BIDS_ROOT/code/sessions_map.tsv"
SOURCE_PATH="$RAW_ROOT/$SCANNER_ID/NIFTI"
MAPPINGS_DIR="$BIDS_ROOT/code/mappings"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Validate inputs ──────────────────────────────────────────────────────────

if [ ! -f "$SESSIONS_MAP" ]; then
    echo "Error: sessions_map.tsv not found at $SESSIONS_MAP"
    echo "Run: python register_subject.py --bids-root $BIDS_ROOT ..."
    exit 1
fi

if [ ! -d "$SOURCE_PATH" ]; then
    echo "Error: Source NIFTI directory not found: $SOURCE_PATH"
    exit 1
fi

# ── Resolve subject ID from sessions_map ─────────────────────────────────────

SES_LABEL="ses-$(printf '%02d' $SESSION 2>/dev/null || echo $SESSION)"
SUBJECT=$(python3 -c "
import csv, sys
ses = '$SES_LABEL'
sid = '$SCANNER_ID'
with open('$SESSIONS_MAP') as f:
    for row in csv.DictReader(f, delimiter='\t'):
        if row['scanner_id'].strip() == sid and row['session_id'].strip() == ses:
            print(row['participant_id'].replace('sub-','').strip())
            sys.exit(0)
sys.exit(1)
" 2>/dev/null) || {
    echo "Error: scanner_id='$SCANNER_ID' session='$SES_LABEL' not found in $SESSIONS_MAP"
    echo "Run: python register_subject.py --bids-root $BIDS_ROOT --scanner-id $SCANNER_ID --session $SESSION ..."
    exit 1
}

echo "Resolved: scanner_id=$SCANNER_ID → sub-$SUBJECT $SES_LABEL"
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
    --sessions-map "$SESSIONS_MAP" \
    --scanner-id "$SCANNER_ID" \
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
    --sessions-map "$SESSIONS_MAP" \
    --scanner-id "$SCANNER_ID" \
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
