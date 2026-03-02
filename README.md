# MPIpe: MRI Processing Pipeline for BIDS Conversion

A two-stage Python pipeline for converting neuroimaging data from NIfTI format to BIDS
(Brain Imaging Data Structure) compliant organisation.
Designed for the MPI for Biological Cybernetics, it supports two source layouts:

| Mode | Source layout | Typical use-case |
|------|--------------|-----------------|
| **files** (default) | Flat `.nii.gz` / `.json` files | Standard dcm2niix output |
| **folders** | One sub-directory per series | Multi-sequence / multi-run studies |

## Overview

The pipeline has two stages:

1. **`generate_bids_config.py`** — scans the source and writes a YAML mapping.
2. **`copy2bids.py`** — reads the mapping and organises files into a BIDS tree.

## Features

- **Automatic detection**: T1w anatomical, BOLD functional (EPI + bSSFP), GRE / reversed-PE fieldmaps, B1 maps
- **Duplicate deduplication** *(folders mode)*: when the same series is re-acquired, only the run with the highest numeric prefix is kept
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

## Stage 1 — generate_bids_config.py

### files mode (default)

Scans `*.nii` / `*.nii.gz` directly in `--source`.
Produces a **flat** mapping (no session wrapper).

```bash
# Auto-detect everything
python generate_bids_config.py \\
  --source /path/to/nifti_files \\
  --out mapping.yaml

# Force all BOLD to task "vision"
python generate_bids_config.py \\
  --source /path/to/nifti_files \\
  --force-task vision \\
  --no-prompt \\
  --out mapping.yaml

# Rename an auto-detected task
python generate_bids_config.py \\
  --source /path/to/nifti_files \\
  --task-rename rest=motor
```

### folders mode

Scans immediate sub-directories of `--source` (one folder per series).
Produces a **session-wrapped** mapping (`ses-{session}: ...`).

```bash
python generate_bids_config.py \\
  --mode folders \\
  --source /path/to/series_folders \\
  --task prf \\
  --session 01 \\
  --out mapping.yaml
```

### Options reference

| Option | Mode | Description |
|--------|------|-------------|
| `--source` | both | Source directory |
| `--out` | both | Output YAML file (default: `mapping.yaml`) |
| `--mode` | both | `files` (default) or `folders` |
| `--no-prompt` | both | Skip confirmation prompt |
| `--force-task NAME` | files | Assign all BOLD runs to this task |
| `--task-rename OLD=NEW` | files | Rename a detected task (repeatable) |
| `--task NAME` | folders | Task name for functional data (default: `task`) |
| `--session ID` | folders | Session ID written as mapping key (default: `01`) |

---

## Stage 2 — copy2bids.py

### files mode (default)

```bash
python copy2bids.py \\
  --source /path/to/nifti_files \\
  --dest   /path/to/bids_root \\
  --config mapping.yaml \\
  --method link

# With events files and dry-run preview
python copy2bids.py \\
  --source /path/to/nifti_files \\
  --dest   /path/to/bids_root \\
  --config mapping.yaml \\
  --events-dir /path/to/events \\
  --dry
```

### folders mode

```bash
# Dry run
python copy2bids.py \\
  --mode folders \\
  --source /path/to/series_folders \\
  --dest   /path/to/bids_root \\
  --config mapping.yaml \\
  --subject 01 \\
  --session 02 \\
  --dry

# Actual conversion
python copy2bids.py \\
  --mode folders \\
  --source /path/to/series_folders \\
  --dest   /path/to/bids_root \\
  --config mapping.yaml \\
  --subject 01 \\
  --session 02
```

### Options reference

| Option | Mode | Description |
|--------|------|-------------|
| `--source` | both | Source directory |
| `--dest` | both | BIDS dataset root (created if absent) |
| `--config` | both | YAML/JSON mapping file |
| `--mode` | both | `files` (default) or `folders` |
| `--subject` | both | Subject ID (default: basename of `--source`) |
| `--session` | both | Session label in BIDS filenames (default: `01`) |
| `--method` | both | `copy`, `link`, or `symlink` (default: `copy`) |
| `--events-dir` | files | Directory with `*_events.tsv` files |
| `--dry` | both | Dry-run — print actions without writing |

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

> **Note (folders mode):** if `run01` appears twice the mapping keeps only the **last**
> (highest-prefix) folder. Always review the generated mapping before running the conversion.

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
