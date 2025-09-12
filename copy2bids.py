#!/usr/bin/env python3
"""copy2bids.py - Stage-2 script: copy / hard-link / symlink series into a
BIDS-compatible folder tree **based on a YAML/JSON mapping** produced by
*generate_bids_config.py* (or edited by hand).

Assumptions & highlights
------------------------
* **Single-session dataset** → session name is hard-wired as ``ses-01``.
* Works with *already converted* NIfTI + JSON sidecars - one file pair per
  series.
* Mapping file structure (YAML or JSON) **must** look like::

    anat:
      T1w:
        - 0008_ADNI_192slices_64channel

    func:
      rest:
        run-01:
          bold: 0010_cmrr_mbep2d_bold_64ch_MB2_GRAPPA2_2mm_PRG_TR2000
          sbref: 0009_cmrr_mbep2d_bold_64ch_MB2_GRAPPA2_2mm_PRG_TR2000_SBRef
        run-02:
          bold: 0012_cmrr_mbep2d_bold_64ch_MB2_GRAPPA2_2mm_PRG_TR2000

    fmap:
      gre:
        magnitude1: 0025_gre_field_mapping_e1
        phase1:     0025_gre_field_mapping_e2
        phase2:     0026_gre_field_mapping_e2_ph

* The **series names** (e.g. ``0010_cmrr_…``) are *stems* - the ``.nii.gz``
  and matching ``.json`` must exist in `--source`.
* The **subject ID** defaults to the *leaf directory name* of `--source` but
  can be overridden with ``--subject``.
* Optional ``--events-dir``: the script looks for files named
  ``task-<task>_run-<NN>_events.tsv`` and copies them next to the BOLD run.
* Three copy modes: ``copy`` (shutil.copy2), ``link`` (hard-link),
  ``symlink`` (relative symlink).
* Add ``--dry`` for a dry-run (print what would happen).

Usage example
-------------

```bash
python copy2bids.py \
    --source /data/GCCP-KVKI/DICOM_NIFTI \
    --dest   /data/BIDS_root \
    --config mapping.yaml \
    --events-dir /data/onsets \
    --method link            # copy|link|symlink
```
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # will still support JSON configs

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def load_mapping(cfg_path: Path) -> Dict[str, Any]:
    """Load YAML or JSON mapping file."""
    text = cfg_path.read_text()
    if cfg_path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            sys.exit("PyYAML is required to read YAML configs - install with `pip install pyyaml`.")
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"Config file not valid JSON or YAML: {e}")


def copy_file(src: Path, dst: Path, method: str, dry: bool = False):
    """Copy/link a file depending on *method* (copy|link|symlink)."""
    if dry:
        print(f" [DRY] {method.upper():6} {src} -> {dst}")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    if method == "copy":
        shutil.copy2(src, dst)
    elif method == "link":
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    elif method == "symlink":
        if dst.exists():
            dst.unlink()
        rel = os.path.relpath(src, dst.parent)
        os.symlink(rel, dst)
    else:  # pragma: no cover
        raise ValueError(f"Unknown method: {method}")


def build_dest_name(subject: str, session: str, suffix: str, ext: str = ".nii.gz") -> str:
    return f"sub-{subject}_ses-{session}_{suffix}{ext}"

# -----------------------------------------------------------------------------
# Main routine
# -----------------------------------------------------------------------------

def main():  # noqa: C901 (complex but clear)
    p = argparse.ArgumentParser(description="Copy/link NIfTI series into a BIDS tree using a mapping (single-session)")
    p.add_argument("--source", required=True, type=Path, help="Folder with *.nii.gz / *.json series")
    p.add_argument("--dest", required=True, type=Path, help="Root of BIDS dataset (will be created if absent)")
    p.add_argument("--config", required=True, type=Path, help="YAML or JSON mapping file")
    p.add_argument("--events-dir", type=Path, help="Folder with *_events.tsv files [optional]")
    p.add_argument("--subject", help="Override subject ID [default: basename of --source]")
    p.add_argument("--method", choices=["copy", "link", "symlink"], default="copy", help="Copy method [link]")
    p.add_argument("--dry", action="store_true", help="Dry-run - print actions but don't write")
    args = p.parse_args()

    # ---------------- Validate paths ----------------
    if not args.source.is_dir():
        sys.exit(f"Source directory not found: {args.source}")
    if not args.config.is_file():
        sys.exit(f"Config file not found: {args.config}")
    if args.events_dir and not args.events_dir.is_dir():
        sys.exit(f"Events directory not found: {args.events_dir}")

    subject = args.subject or args.source.name
    session = "01"  # one-session rule

    mapping = load_mapping(args.config)

    # ---------------- Copy anatomical ----------------
    for label, series_list in mapping.get("anat", {}).items():
        for stem in series_list:
            for ext in (".nii.gz", ".json"):
                src = args.source / f"{stem}{ext}"
                if not src.exists():
                    print(f"WARNING - missing file {src}")
                    continue
                dst = args.dest / f"sub-{subject}" / f"ses-{session}" / "anat" / build_dest_name(subject, session, label, ext)
                copy_file(src, dst, args.method, args.dry)

    # ---------------- Copy functional ----------------
    for task, runs in mapping.get("func", {}).items():
        for run_label, entry in runs.items():
            bold_stem = entry["bold"]
            sbref_stem = entry.get("sbref")
            for stem, suffix in ((bold_stem, "bold"), (sbref_stem, "sbref") if sbref_stem else ()):  # type: ignore
                if stem is None:
                    continue
                for ext in (".nii.gz", ".json"):
                    src = args.source / f"{stem}{ext}"
                    if not src.exists():
                        print(f"WARNING - missing file {src}")
                        continue
                    bids_suffix = f"task-{task}_" + run_label + f"_{suffix}"
                    dst = args.dest / f"sub-{subject}" / f"ses-{session}" / "func" / build_dest_name(subject, session, bids_suffix, ext)
                    copy_file(src, dst, args.method, args.dry)

            # ---- events ----
            if args.events_dir and not args.dry:
                events_src = args.events_dir / f"task-{task}_{run_label}_events.tsv"
                if events_src.exists():
                    events_dst = args.dest / f"sub-{subject}" / f"ses-{session}" / "func" / build_dest_name(subject, session, f"task-{task}_{run_label}_events", ".tsv")
                    copy_file(events_src, events_dst, args.method, args.dry)
                else:
                    print(f"Note: no events file found for {task} {run_label}")

    # ---------------- Copy fieldmaps ----------------
    for fmap_type, fmap_dict in mapping.get("fmap", {}).items():
        for key, stem in fmap_dict.items():
            for ext in (".nii.gz", ".json"):
                src = args.source / f"{stem}{ext}"
                if not src.exists():
                    print(f"WARNING - missing file {src}")
                    continue
                bids_suffix = key  # magnitude1 / phase1 / phase2
                dst = args.dest / f"sub-{subject}" / f"ses-{session}" / "fmap" / build_dest_name(subject, session, bids_suffix, ext)
                copy_file(src, dst, args.method, args.dry)

    print("\n✔ Done (dry-run)" if args.dry else "\n✔ Finished copying/linking.")


if __name__ == "__main__":
    main()
