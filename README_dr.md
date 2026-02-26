# BIDS conversion workflow that:

**1. Generates mapping files using `generate_bids_config_dr.py`:**

Automatically scans your folder structure
Ignores test runs
Creates proper BIDS mapping for your data

**2. Converts to BIDS format using `copy2bids_dr.py`:**
- Takes custom subject and session IDs as required parameters
- Handles folder-based source data structure
- Creates proper BIDS directory structure and filenames
- Supports copy, hard-link, or symlink operations
- Make sure "Pattern" in the mapping file matches your actual filenames 

Almost the same as `generate_bids_config.py` and `copy2bids.py` by Lucas Mahler, but adapted for multi-session data and ignores test runs.
If run01 exists twice, it will only map the **LAST** one. Make sure to always check the generated mapping file!

Author: Dana Ramadan
Date: 26 August 2025

# Usage

```bash
# Generate mapping
python generate_bids_config_dr.py \
  --source ~/mrdata/mri_etl_s94t/studies/116/experiments/DTIM-XTAP/NIFTI/ \
  --task prf \
  --no-prompt

# Convert to BIDS (dry run)
python copy2bids_dr.py \
  --source ~/mrdata/mri_etl_s94t/studies/116/experiments/DTIM-XTAP/NIFTI/ \
  --dest /path/to/bids/dataset \
  --config mapping_dr.yaml \
  --subject 01 \
  --session 01 \
  --dry

# Actual conversion
python copy2bids_dr.py \
  --source ~/mrdata/mri_etl_s94t/studies/116/experiments/DTIM-XTAP/NIFTI/ \
  --dest /path/to/bids/dataset \
  --config mapping_dr.yaml \
  --subject 01 \
  --session 01

```
