#!/bin/bash

# BIDS Conversion Script
# Usage: ./convert_to_bids.sh <source_path> <subject_id> <session_id>
# Example: ./convert_to_bids.sh /home/dramadan/mrdata/mri_etl_s94t/studies/116/experiments/DTIM-XTAP/NIFTI 01 01
# or: ./convert_to_bids.sh DTIM-XTAP 01 01 (for backward compatibility)

# Check if correct number of arguments provided
if [ $# -ne 3 ]; then
    echo "Usage: $0 <source_path_or_experiment_name> <subject_id> <session_id>"
    echo "Examples:"
    echo "  $0 /full/path/to/NIFTI/folder 01 01"
    echo "  $0 DTIM-XTAP 01 01"
    exit 1
fi

# Store arguments
SOURCE_ARG=$1
SUBJECT=$2
SESSION=$3

# Determine if first argument is a full path or experiment name
if [[ "$SOURCE_ARG" == /* ]]; then
    # Full path provided
    SOURCE_PATH="$SOURCE_ARG"
    EXPERIMENT=$(basename $(dirname "$SOURCE_ARG"))
else
    # Experiment name provided - construct path
    EXPERIMENT="$SOURCE_ARG"
    SOURCE_PATH="~/mrdata/mri_etl_s94t/studies/116/experiments/$EXPERIMENT/NIFTI/"
fi

# Expand tilde and check if source directory exists
EXPANDED_SOURCE=$(eval echo "$SOURCE_PATH")
if [ ! -d "$EXPANDED_SOURCE" ]; then
    echo "Error: Source directory not found: $EXPANDED_SOURCE"
    echo "Please check the path or experiment name."
    exit 1
fi

echo "Source directory: $EXPANDED_SOURCE"

# Create log file path
LOG_DIR="~/data/prf/bids_dataset/sub-${SUBJECT}/ses-${SESSION}"
LOG_FILE="${LOG_DIR}/bids_conversion.log"

echo "Starting BIDS conversion for experiment: $EXPERIMENT, subject: $SUBJECT, session: $SESSION"
echo "Source: $EXPANDED_SOURCE"
echo "Log file will be saved to: $LOG_FILE"

# Create log directory if it doesn't exist
mkdir -p "$(eval echo $LOG_DIR)"

# Start logging (redirect all output to both terminal and log file)
exec > >(tee -a "$(eval echo $LOG_FILE)") 2>&1

echo "=== BIDS Conversion Log ===" 
echo "Date: $(date)"
echo "Experiment: $EXPERIMENT"
echo "Subject: $SUBJECT" 
echo "Session: $SESSION"
echo "=========================="

# 1) Activate the prf-pipeline environment
echo "Activating prf-pipeline environment..."
source ~/python-envs/prf-pipeline/bin/activate

# Check if activation was successful
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate prf-pipeline environment"
    exit 1
fi

# 2) Run generate_bids_config_dr.py
echo "Generating BIDS mapping configuration..."
python generate_bids_config_dr.py \
  --source "$EXPANDED_SOURCE" \
  --task prf \
  --session "$SESSION" \
  --no-prompt

# Check if mapping generation was successful
if [ $? -ne 0 ]; then
    echo "Error: Failed to generate BIDS mapping"
    exit 1
fi

echo "BIDS mapping generated successfully."

# 2.5) Create BIDS dataset directory if it doesn't exist
BIDS_DEST="~/data/prf/bids_dataset"
EXPANDED_DEST=$(eval echo "$BIDS_DEST")
if [ ! -d "$EXPANDED_DEST" ]; then
    echo "Creating BIDS dataset directory: $EXPANDED_DEST"
    mkdir -p "$EXPANDED_DEST"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create BIDS dataset directory"
        exit 1
    fi
fi

# 3) Run copy2bids_dr.py with dry run only
echo "Running BIDS conversion (DRY RUN only)..."
python copy2bids_dr.py \
  --source "$EXPANDED_SOURCE" \
  --dest ~/data/prf/bids_dataset/ \
  --config mapping_dr.yaml \
  --subject $SUBJECT \
  --session $SESSION \
  --dry

# Check if dry run was successful
if [ $? -ne 0 ]; then
    echo "Error: Dry run failed"
    exit 1
fi

echo ""
echo "✅ BIDS conversion dry run completed successfully!"
echo "📁 Experiment: $EXPERIMENT"
echo "👤 Subject: $SUBJECT"
echo "📅 Session: $SESSION"
echo ""

# Prompt user if they want to proceed with actual conversion
read -p "Are you happy with the dry run results? Proceed with actual conversion? [Y/n]: " -n 1 -r
echo    # Move to a new line
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    echo "Proceeding with actual BIDS conversion..."
    
    # Run the actual conversion (without --dry flag)
    python copy2bids_dr.py \
      --source "$EXPANDED_SOURCE" \
      --dest ~/data/prf/bids_dataset/ \
      --config mapping_dr.yaml \
      --subject $SUBJECT \
      --session $SESSION
    
    # Check if actual conversion was successful
    if [ $? -ne 0 ]; then
        echo "Error: Actual conversion failed"
        exit 1
    fi
    
    echo ""
    echo "🎉 BIDS conversion completed successfully!"
    echo "📂 Files have been copied to: ~/data/prf/bids_dataset/"
    echo "📝 Log saved to: $LOG_FILE"
else
    echo "Conversion cancelled. No files were copied."
    echo "📝 Log saved to: $LOG_FILE"
    echo ""
    echo "To run the actual conversion later, use:"
    echo "python copy2bids_dr.py \\"
    echo "  --source \"$EXPANDED_SOURCE\" \\"
    echo "  --dest ~/data/prf/bids_dataset/ \\"
    echo "  --config mapping_dr.yaml \\"
    echo "  --subject $SUBJECT \\"
    echo "  --session $SESSION"
fi

echo ""
echo "=== End of BIDS Conversion Log ==="
echo "Completed at: $(date)"
