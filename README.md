# MPIpe: MRI Processing Pipeline for BIDS Conversion

A three-stage Python pipeline for converting neuroimaging data from NIfTI format to BIDS
(Brain Imaging Data Structure) compliant organisation.
Designed for the MPI for Biological Cybernetics, it supports two source layouts:

| Mode | Source layout | Typical use-case |
|------|--------------|-----------------|
| **files** (default) | Flat `.nii.gz` / `.json` files | Standard dcm2niix output |
| **folders** | One sub-directory per series | Multi-sequence / multi-run studies |

## Overview

The pipeline has three stages:

1. **`register_subject.py`** — enroll a new subject/session; records pseudonym → BIDS ID mapping.
2. **`generate_bids_config.py`** — scans the source and writes a YAML scan mapping.
3. **`copy2bids.py`** — reads the mapping and organises files into a BIDS tree.

`convert_to_bids.sh` orchestrates stages 2 and 3 in one command.

## Features

- **CSV-driven batch mode**: provide a subject list CSV and generate configs / copy files for all subjects in one command
- **Pseudonym mapping**: scanner IDs and behavioral IDs are mapped to BIDS subject IDs in a single version-controlled file (`code/sessions_map.tsv`), supporting subjects scanned under different pseudonyms across sessions
- **Automatic detection**: T1w anatomical, BOLD functional (EPI + bSSFP), GRE / reversed-PE fieldmaps, B1 maps
- **Duplicate deduplication** *(folders mode, opt-in)*: when the same series is re-acquired, pass `--dedup` to keep only the highest-prefix folder
- **Test-run skipping** *(folders mode)*: folders matching "test", "localizer", "scout" etc. are ignored automatically
- **BIDS-enriched JSON sidecars** *(folders mode)*: `TaskName`, `SequenceType` and `PhaseEncodingDirection` are injected
- **Flexible task naming**: `--force-task` (files) or `--task` (folders)
- **Multiple copy methods**: `copy`, `link` (hard-link), `symlink`
- **SBRef support** *(files mode)*
- **Events integration** *(files mode)*: optional `*_events.tsv` copying
- **Dry-run mode**: preview every action before executing

## Requirements

```bash
pip install pyyaml
```

---

## Pseudonym mapping & reproducibility

Raw data folders are named with scanner-assigned pseudonyms (e.g. `TYCM-RTYX`).
Behavioral/stimulus files use a separate pseudonym system. Neither can be derived from the other.

Two files at the BIDS root track all ID relationships:

| File | Purpose |
|------|---------|
| `participants.tsv` | BIDS standard; one row per subject; demographics only (no pseudonyms) |
| `code/sessions_map.tsv` | Per-session map: `participant_id`, `session_id`, `scanner_id`, `beh_id` |

**`code/sessions_map.tsv` example:**
```
participant_id  session_id  scanner_id    beh_id
sub-01          ses-01      TYCM-RTYX     P0042_S1
sub-01          ses-02      ABCD-EFGH     P0042_S2
sub-02          ses-01      ROP4-O4DC     P0031_S1
```

Both files are version-controlled inside the BIDS dataset. Commit them immediately after enrollment.

---

## Stage 0 — register_subject.py

Run once per session before conversion. Creates or appends to `participants.tsv` and `code/sessions_map.tsv`.

```bash
# New subject, new session
python register_subject.py \
  --bids-root /data/BIDS \
  --scanner-id TYCM-RTYX \
  --session 01 \
  --beh-id P0042_S1 \
  --age 28 --sex F

# Existing subject (sub-01), second session under a new scanner pseudonym
python register_subject.py \
  --bids-root /data/BIDS \
  --scanner-id ABCD-EFGH \
  --session 02 \
  --beh-id P0042_S2 \
  --subject 01
```

Then commit:
```bash
git -C /data/BIDS add participants.tsv code/sessions_map.tsv
git -C /data/BIDS commit -m "Enroll sub-01 ses-01 (TYCM-RTYX)"
```

### Options reference

| Option | Required | Description |
|--------|----------|-------------|
| `--bids-root` | yes | BIDS dataset root directory |
| `--scanner-id` | yes | Scanner pseudonym (raw folder name) |
| `--session` | yes | Session number (e.g. `01`) |
| `--beh-id` | yes | Behavioral/stimulus pseudonym for this session |
| `--subject` | no | BIDS subject number; auto-increments if omitted |
| `--age` | no | Age at first session (default: `n/a`) |
| `--sex` | no | Biological sex M/F (default: `n/a`) |

---

## Stage 1 — generate_bids_config.py

### Batch mode (CSV — recommended)

Process every subject in a CSV at once. Source paths are derived as `<source-base>/<Pseudonym>/NIFTI/`.
Output files are written to `<out-dir>/sub-{ID}_ses-{session}_mapping.yaml`.
No confirmation prompt — configs are written directly.

```bash
python generate_bids_config.py \
  --csv NRBR_subject_list.csv \
  --source-base /data/raw \
  --out-dir /data/BIDS/code/mappings \
  --mode folders --task prf --session 01 --dedup
```

Subjects whose source directory is missing are skipped with a `[WARN]` message.
Subjects with a `Comments` field are processed normally but flagged with `[NOTE: ...]` in the output.

### Single-subject — files mode

Scans `*.nii` / `*.nii.gz` directly in `--source`.
Produces a **flat** mapping (no session wrapper).

```bash
# Auto-detect everything
python generate_bids_config.py \
  --source /path/to/nifti_files \
  --out mapping.yaml

# Force all BOLD to task "vision"
python generate_bids_config.py \
  --source /path/to/nifti_files \
  --force-task vision \
  --no-prompt \
  --out mapping.yaml

# Rename an auto-detected task
python generate_bids_config.py \
  --source /path/to/nifti_files \
  --task-rename rest=motor
```

### Single-subject — folders mode

Scans immediate sub-directories of `--source` (one folder per series).
Produces a **session-wrapped** mapping (`ses-{session}: ...`).

```bash
python generate_bids_config.py \
  --mode folders \
  --source /data/raw/TYCM-RTYX/NIFTI \
  --task prf \
  --session 01 \
  --subject 01 \
  --out-dir /data/BIDS/code/mappings \
  --no-prompt
```

### Options reference

| Option | Mode | Description |
|--------|------|-------------|
| `--csv PATH` | batch | Subject list CSV (columns: `Pseudonym`, `BIDS-ID`, `Comments`, …) |
| `--source-base PATH` | batch | Base directory for raw data; **required** with `--csv` |
| `--source PATH` | single | Source directory *(mutually exclusive with `--csv`)* |
| `--out-dir PATH` | both | Write to `<path>/sub-{subject}_ses-{session}_mapping.yaml`; **required** with `--csv` |
| `--out PATH` | single | Output YAML file (default: `mapping.yaml`) |
| `--mode` | both | `files` (default) or `folders` |
| `--no-prompt` | single | Skip confirmation prompt *(batch mode never prompts)* |
| `--force-task NAME` | files | Assign all BOLD runs to this task |
| `--task-rename OLD=NEW` | files | Rename a detected task (repeatable) |
| `--task NAME` | folders | Task name for functional data (default: `task`) |
| `--session ID` | folders | Session ID written as mapping key (default: `01`) |
| `--subject ID` | single/folders | BIDS subject label; used with `--out-dir` for auto-naming |
| `--dedup` | folders | Keep only the highest-prefix folder per series name (for aborted+repeated scans) |

---

## Stage 2 — copy2bids.py

### Batch mode (CSV — recommended)

Process every subject at once using configs generated in Stage 1.
Config files are looked up automatically as `<config-dir>/sub-{ID}_ses-{session}_mapping.yaml`.

```bash
# Dry-run preview
python copy2bids.py \
  --csv NRBR_subject_list.csv \
  --source-base /data/raw \
  --config-dir /data/BIDS/code/mappings \
  --dest /data/BIDS \
  --mode folders --method link --dry

# Full run
python copy2bids.py \
  --csv NRBR_subject_list.csv \
  --source-base /data/raw \
  --config-dir /data/BIDS/code/mappings \
  --dest /data/BIDS \
  --mode folders --method link
```

Subjects with a missing source directory or missing config file are skipped with a `[WARN]` message.

### Single-subject — files mode

```bash
python copy2bids.py \
  --source /path/to/nifti_files \
  --dest   /path/to/bids_root \
  --config mapping.yaml \
  --method link

# With events files and dry-run preview
python copy2bids.py \
  --source /path/to/nifti_files \
  --dest   /path/to/bids_root \
  --config mapping.yaml \
  --events-dir /path/to/events \
  --dry
```

### Single-subject — folders mode

```bash
# Resolve subject/session automatically from sessions_map.tsv
python copy2bids.py \
  --mode folders \
  --source /data/raw/TYCM-RTYX/NIFTI \
  --dest   /data/BIDS \
  --config /data/BIDS/code/mappings/sub-01_ses-01_mapping.yaml \
  --sessions-map /data/BIDS/code/sessions_map.tsv \
  --scanner-id TYCM-RTYX \
  --dry

# Or provide subject/session explicitly (no sessions_map needed)
python copy2bids.py \
  --mode folders \
  --source /path/to/series_folders \
  --dest   /path/to/bids_root \
  --config mapping.yaml \
  --subject 01 \
  --session 02
```

### Options reference

| Option | Mode | Description |
|--------|------|-------------|
| `--csv PATH` | batch | Subject list CSV (columns: `Pseudonym`, `BIDS-ID`, …) |
| `--source-base PATH` | batch | Base directory for raw data; **required** with `--csv` |
| `--config-dir PATH` | batch | Directory containing per-subject YAML configs; **required** with `--csv` |
| `--source PATH` | single | Source directory *(mutually exclusive with `--csv`)* |
| `--config PATH` | single | YAML/JSON mapping file; **required** without `--csv` |
| `--dest PATH` | both | BIDS dataset root (created if absent) |
| `--mode` | both | `files` (default) or `folders` |
| `--subject` | single | Subject ID (default: basename of `--source`) |
| `--session` | both | Session label in BIDS filenames (default: `01`) |
| `--method` | both | `copy`, `link`, or `symlink` (default: `copy`) |
| `--events-dir` | files | Directory with `*_events.tsv` files |
| `--dry` | both | Dry-run — print actions without writing |
| `--sessions-map PATH` | single | Path to `sessions_map.tsv`; resolves subject/session from scanner pseudonym |
| `--scanner-id ID` | single | Scanner pseudonym; looked up in `--sessions-map` |

---

## Mapping file format

### files mode (flat)

```yaml
anat:
  T1w:
    - 0003_ADNI_192slices_64channel

func:
  vision:
    run-01:
      bold: 0005_cmrr_mbep2d_bold_64ch_MB2_GRAPPA2_2mm_PRG_TR2000
      sbref: 0004_cmrr_mbep2d_bold_64ch_MB2_GRAPPA2_2mm_PRG_TR2000_SBRef
    run-02:
      bold: 0007_cmrr_mbep2d_bold_64ch_MB2_GRAPPA2_2mm_PRG_TR2000

fmap:
  gre:
    magnitude1: 0016_gre_field_mapping_e1
    phase1:     0016_gre_field_mapping_e2
    phase2:     0017_gre_field_mapping_e2_ph
```

### folders mode (session-wrapped)

```yaml
ses-01:
  anat:
    T1w:
      - 00005_db_MPRAGE_0p60_UP_opt_prot
  func:
    prf:
      run-01:
        bssfp: 00011_3DbSSFP_TR4206ms_B1vol_run01
        epi:   00012_dzne_ep3d_TR4200ms_B1vol_run01
      run-02:
        bssfp: 00019_3DbSSFP_TR4206ms_B1vol_run02
        epi:   00020_dzne_ep3d_TR4200ms_B1vol_run02
  fmap:
    dir:
      PA:    00013_dzne_ep3d_TR4200ms_B1vol_revPE
      b1map: 00017_tfl_b1map_2mm_B1vol
```

> **Note (folders mode):** by default all folders are kept and assigned sequential run numbers.
> Pass `--dedup` if a scan was aborted and restarted — it then keeps only the highest-prefix folder per series name.
> Always review the generated mapping before running the conversion.

---

## Detection heuristics

### files mode

| Category | Label | Pattern matched |
|----------|-------|----------------|
| Anat | T1w | `T1`, `ADNI`, `MPRAGE` |
| Func | bold | `bold`, `ep3d`, `3DbSSFP` |
| Fmap | gre | `field`, `gre`, `revPE` |
| *Skip* | — | `localizer`, `scout` |

SBRef: any file matching `SBRef` is held and attached to the next BOLD run.

### folders mode

| Category | Label | Pattern matched |
|----------|-------|----------------|
| Anat | T1w | `MPRAGE`, `T1`, `anatomical` |
| Func | epi | `ep3d`, `epi`, `bold` |
| Func | bssfp | `3DbSSFP`, `bssfp`, `ssfp` |
| Fmap | PA (revPE) | `revPE`, `reversed`, `topup`, `PA` |
| Fmap | b1map | `b1map` |
| *Skip* | — | `localizer`, `scout`, `B0_Map`, `aa_B0Mapping`, `replaced_`, `test` |

Fieldmaps are matched **before** functional series so reversed-PE folders are not
misclassified as EPI.

---

## Output structure

### files mode
```
bids_root/
└── sub-{subject}/
    └── ses-{session}/
        ├── anat/
        │   ├── sub-{subject}_ses-{session}_T1w.nii.gz
        │   └── sub-{subject}_ses-{session}_T1w.json
        ├── func/
        │   ├── sub-{subject}_ses-{session}_task-{task}_run-01_bold.nii.gz
        │   ├── sub-{subject}_ses-{session}_task-{task}_run-01_bold.json
        │   ├── sub-{subject}_ses-{session}_task-{task}_run-01_sbref.nii.gz
        │   └── sub-{subject}_ses-{session}_task-{task}_run-01_events.tsv
        └── fmap/
            ├── sub-{subject}_ses-{session}_magnitude1.nii.gz
            ├── sub-{subject}_ses-{session}_phase1.nii.gz
            └── sub-{subject}_ses-{session}_phase2.nii.gz
```

### folders mode
```
bids_root/
├── participants.tsv
├── participants.json
├── code/
│   ├── sessions_map.tsv
│   ├── mappings/
│   │   ├── sub-01_ses-01_mapping.yaml
│   │   └── sub-01_ses-02_mapping.yaml
│   ├── register_subject.py
│   ├── generate_bids_config.py
│   └── copy2bids.py
└── sub-{subject}/
    └── ses-{session}/
        ├── anat/
        │   └── sub-{subject}_ses-{session}_T1w.nii.gz
        ├── func/
        │   ├── sub-{subject}_ses-{session}_task-{task}_acq-epi_run-01_bold.nii.gz
        │   ├── sub-{subject}_ses-{session}_task-{task}_acq-bssfp_run-01_bold.nii.gz
        │   └── ...
        └── fmap/
            ├── sub-{subject}_ses-{session}_dir-PA_epi.nii.gz
            └── sub-{subject}_ses-{session}_TB1map.nii.gz
```

---

## Full reproducible workflow

### Batch workflow (multiple subjects from CSV)

```bash
# Step 0 — enroll subjects (once per session, per subject)
python register_subject.py \
  --bids-root /data/BIDS \
  --scanner-id TYCM-RTYX --session 01 \
  --beh-id P0042_S1 --age 28 --sex F
git -C /data/BIDS add participants.tsv code/sessions_map.tsv
git -C /data/BIDS commit -m "Enroll subjects"

# Step 1 — generate configs for all subjects in CSV
python generate_bids_config.py \
  --csv NRBR_subject_list.csv \
  --source-base /data/raw \
  --out-dir /data/BIDS/code/mappings \
  --mode folders --task prf --session 01 --dedup
# Review/edit the generated YAMLs before proceeding
git -C /data/BIDS add code/mappings/
git -C /data/BIDS commit -m "Add scan mappings for all subjects"

# Step 2 — dry-run preview
python copy2bids.py \
  --csv NRBR_subject_list.csv \
  --source-base /data/raw \
  --config-dir /data/BIDS/code/mappings \
  --dest /data/BIDS \
  --mode folders --method link --dry

# Step 3 — actual copy
python copy2bids.py \
  --csv NRBR_subject_list.csv \
  --source-base /data/raw \
  --config-dir /data/BIDS/code/mappings \
  --dest /data/BIDS \
  --mode folders --method link
```

### Single-subject workflow

```bash
# Step 0 — enroll
python register_subject.py \
  --bids-root /data/BIDS \
  --scanner-id TYCM-RTYX --session 01 \
  --beh-id P0042_S1 --age 28 --sex F
git -C /data/BIDS add participants.tsv code/sessions_map.tsv
git -C /data/BIDS commit -m "Enroll sub-01 ses-01 (TYCM-RTYX)"

# Step 1 — generate scan mapping
python generate_bids_config.py \
  --mode folders \
  --source /data/raw/TYCM-RTYX/NIFTI \
  --task prf --session 01 --subject 01 \
  --out-dir /data/BIDS/code/mappings --no-prompt
git -C /data/BIDS add code/mappings/sub-01_ses-01_mapping.yaml
git -C /data/BIDS commit -m "Add scan mapping sub-01 ses-01"

# Step 2 — dry run
python copy2bids.py \
  --mode folders \
  --source /data/raw/TYCM-RTYX/NIFTI \
  --dest /data/BIDS \
  --config /data/BIDS/code/mappings/sub-01_ses-01_mapping.yaml \
  --sessions-map /data/BIDS/code/sessions_map.tsv \
  --scanner-id TYCM-RTYX --dry

# Step 3 — actual copy
python copy2bids.py \
  --mode folders \
  --source /data/raw/TYCM-RTYX/NIFTI \
  --dest /data/BIDS \
  --config /data/BIDS/code/mappings/sub-01_ses-01_mapping.yaml \
  --sessions-map /data/BIDS/code/sessions_map.tsv \
  --scanner-id TYCM-RTYX --method link
```

Or run stages 1–3 for a single subject in one command:

```bash
./convert_to_bids.sh TYCM-RTYX 01 /data/BIDS /data/raw
```
