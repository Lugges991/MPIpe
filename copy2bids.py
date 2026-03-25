#!/usr/bin/env python3
"""copy2bids.py - Stage-2 script: copy / hard-link / symlink series into a
BIDS-compatible folder tree based on a YAML/JSON mapping produced by
generate_bids_config.py (or edited by hand).

Two modes
---------
files (default)
    Source series are individual *.nii.gz + *.json files directly in --source.
    Mapping has a flat structure (no session wrapper).
    Supports: T1w anat, BOLD (+SBRef) func, GRE magnitude/phase fieldmaps.

folders
    Source series are subdirectories of --source (one folder per series).
    Mapping has a session wrapper  (ses-{session}: ...).
    Supports: T1w anat, EPI + bSSFP func (acq- label added), PA + B1map fmaps.
    JSON sidecars are enriched with TaskName / SequenceType / PhaseEncodingDirection
    for BIDS compliance before being written to the destination.

Common options
--------------
  --session   Session label written into BIDS filenames (default: 01).
              In files mode the session can also be overridden this way.
  --subject   Subject ID (default: basename of --source).
  --method    copy | link | symlink  (default: copy)
  --dry       Print what would be done without touching the filesystem.

Usage examples
--------------
# files mode
python copy2bids.py \\
    --source /data/GCCP-KVKI/NIFTI \\
    --dest   /data/BIDS \\
    --config mapping.yaml \\
    --method link

# folders mode
python copy2bids.py \\
    --mode folders \\
    --source /data/studies/116/NIFTI \\
    --dest   /data/BIDS \\
    --config mapping_dr.yaml \\
    --subject 01 \\
    --session 02 \\
    --dry
"""

import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # will still support JSON configs

# -- Helpers ------------------------------------------------------------------


def load_mapping(cfg_path: Path) -> Dict[str, Any]:
    """Load YAML or JSON mapping file."""
    text = cfg_path.read_text()
    if cfg_path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            sys.exit(
                "PyYAML is required to read YAML configs - install with `pip install pyyaml`."
            )
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"Config file not valid JSON or YAML: {e}")


def copy_file(src: Path, dst: Path, method: str, dry: bool = False):
    """Copy/link a file depending on method (copy|link|symlink)."""
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


def build_dest_name(
    subject: str, session: str, suffix: str, ext: str = ".nii.gz"
) -> str:
    return f"sub-{subject}_ses-{session}_{suffix}{ext}"


def find_nifti_files(folder: Path) -> List[Path]:
    """Find .nii and .nii.gz files inside a folder."""
    files: List[Path] = []
    for pat in ("*.nii.gz", "*.nii"):
        files.extend(folder.glob(pat))
    return files


def find_json_files(folder: Path) -> List[Path]:
    return list(folder.glob("*.json"))


def write_json_with_metadata(
    src_json: Path,
    dst_json: Path,
    seq_type: str,
    method: str,
    dry: bool,
    task_name: str = "task",
):
    """Copy JSON sidecar, injecting TaskName / SequenceType BIDS fields."""
    if dry:
        print(
            f" [DRY] {method.upper():6} {src_json} -> {dst_json} (+TaskName, +SequenceType:{seq_type})"
        )
        return
    try:
        meta = json.loads(src_json.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        meta = {}
    meta["TaskName"] = task_name
    meta["SequenceType"] = seq_type.upper()
    if seq_type.lower() == "bssfp":
        meta["PulseSequenceDetails"] = "bSSFP"
    elif seq_type.lower() == "epi":
        meta["PulseSequenceDetails"] = "EP3D"
    meta.setdefault("PhaseEncodingDirection", "j")
    dst_json.parent.mkdir(parents=True, exist_ok=True)
    dst_json.write_text(json.dumps(meta, indent=2))


def write_fmap_json_with_metadata(
    src_json: Path, dst_json: Path, fmap_type: str, method: str, dry: bool
):
    """Copy fieldmap JSON sidecar, injecting BIDS-required metadata."""
    if dry:
        print(
            f" [DRY] {method.upper():6} {src_json} -> {dst_json} (+fmap metadata:{fmap_type})"
        )
        return
    try:
        meta = json.loads(src_json.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        meta = {}
    if fmap_type == "PA":
        meta.setdefault("IntendedFor", [])
        meta.setdefault("PhaseEncodingDirection", "j-")
    elif fmap_type == "b1map":
        meta.setdefault("Units", "arbitrary")
        meta.setdefault("FlipAngle", [])
    else:
        meta.setdefault("PhaseEncodingDirection", "j")
    dst_json.parent.mkdir(parents=True, exist_ok=True)
    dst_json.write_text(json.dumps(meta, indent=2))


# -- files mode ---------------------------------------------------------------


def run_files_mode(args, subject: str, session: str, mapping: Dict):
    """Original flat-file copy logic."""
    # Anatomical
    for label, series_list in mapping.get("anat", {}).items():
        for stem in series_list:
            for ext in (".nii.gz", ".json"):
                src = args.source / f"{stem}{ext}"
                if not src.exists():
                    print(f"WARNING - missing file {src}")
                    continue
                dst = (
                    args.dest
                    / f"sub-{subject}"
                    / f"ses-{session}"
                    / "anat"
                    / build_dest_name(subject, session, label, ext)
                )
                copy_file(src, dst, args.method, args.dry)

    # Functional
    for task, runs in mapping.get("func", {}).items():
        for run_label, entry in runs.items():
            bold_stem = entry.get("bold")
            sbref_stem = entry.get("sbref")
            for stem, suffix in filter(
                lambda x: x[0], [(bold_stem, "bold"), (sbref_stem, "sbref")]
            ):
                for ext in (".nii.gz", ".json"):
                    src = args.source / f"{stem}{ext}"
                    if not src.exists():
                        print(f"WARNING - missing file {src}")
                        continue
                    bids_suffix = f"task-{task}_{run_label}_{suffix}"
                    dst = (
                        args.dest
                        / f"sub-{subject}"
                        / f"ses-{session}"
                        / "func"
                        / build_dest_name(subject, session, bids_suffix, ext)
                    )
                    copy_file(src, dst, args.method, args.dry)

            # events
            if args.events_dir and not args.dry:
                events_src = args.events_dir / f"task-{task}_{run_label}_events.tsv"
                if events_src.exists():
                    events_dst = (
                        args.dest
                        / f"sub-{subject}"
                        / f"ses-{session}"
                        / "func"
                        / build_dest_name(
                            subject, session, f"task-{task}_{run_label}_events", ".tsv"
                        )
                    )
                    copy_file(events_src, events_dst, args.method, args.dry)
                else:
                    print(f"Note: no events file found for {task} {run_label}")

    # Fieldmaps
    for fmap_type, fmap_dict in mapping.get("fmap", {}).items():
        for key, stem in fmap_dict.items():
            for ext in (".nii.gz", ".json"):
                src = args.source / f"{stem}{ext}"
                if not src.exists():
                    print(f"WARNING - missing file {src}")
                    continue
                dst = (
                    args.dest
                    / f"sub-{subject}"
                    / f"ses-{session}"
                    / "fmap"
                    / build_dest_name(subject, session, key, ext)
                )
                copy_file(src, dst, args.method, args.dry)


# -- folders mode -------------------------------------------------------------


def _ses_key_to_label(ses_key: str) -> str:
    """Strip the 'ses-' prefix and zero-pad if purely numeric."""
    label = ses_key.removeprefix("ses-")
    return label.zfill(2) if label.isdigit() else label


def run_folders_mode(args, subject: str, session: str, mapping: Dict):
    """Folder-based copy logic (one subdirectory per series)."""
    # Mapping has a top-level session key; we ignore it and use args.session
    session_data = next(iter(mapping.values()))
    ses_dir = f"ses-{session.zfill(2)}" if session.isdigit() else f"ses-{session}"

    # Anatomical
    for anat_type, folder_list in session_data.get("anat", {}).items():
        for folder_name in folder_list:
            folder_path = args.source / folder_name
            if not folder_path.exists():
                print(f"WARNING: folder not found: {folder_path}")
                continue
            niftis = find_nifti_files(folder_path)
            if not niftis:
                print(f"WARNING: no NIfTI in {folder_path}")
                continue
            for nf in niftis:
                ext = ".nii.gz" if nf.name.endswith(".nii.gz") else ".nii"
                dst = (
                    args.dest
                    / f"sub-{subject}"
                    / ses_dir
                    / "anat"
                    / build_dest_name(subject, session, anat_type, ext)
                )
                copy_file(nf, dst, args.method, args.dry)
            for jf in find_json_files(folder_path):
                dst = (
                    args.dest
                    / f"sub-{subject}"
                    / ses_dir
                    / "anat"
                    / build_dest_name(subject, session, anat_type, ".json")
                )
                copy_file(jf, dst, args.method, args.dry)

    # Functional
    for task, runs in session_data.get("func", {}).items():
        for run_label, sequences in runs.items():
            for seq_type, folder_name in sequences.items():
                if not folder_name:
                    continue
                folder_path = args.source / folder_name
                if not folder_path.exists():
                    print(f"WARNING: folder not found: {folder_path}")
                    continue
                niftis = find_nifti_files(folder_path)
                if not niftis:
                    print(f"WARNING: no NIfTI in {folder_path}")
                    continue

                acq = seq_type.lower()  # "epi" or "bssfp"
                bids_suffix = f"task-{task}_acq-{acq}_{run_label}_bold"

                for nf in niftis:
                    ext = ".nii.gz" if nf.name.endswith(".nii.gz") else ".nii"
                    dst = (
                        args.dest
                        / f"sub-{subject}"
                        / ses_dir
                        / "func"
                        / build_dest_name(subject, session, bids_suffix, ext)
                    )
                    copy_file(nf, dst, args.method, args.dry)
                for jf in find_json_files(folder_path):
                    dst = (
                        args.dest
                        / f"sub-{subject}"
                        / ses_dir
                        / "func"
                        / build_dest_name(subject, session, bids_suffix, ".json")
                    )
                    write_json_with_metadata(
                        jf, dst, seq_type, args.method, args.dry, task_name=task
                    )

    # Fieldmaps
    for _fmap_group, fmap_data in session_data.get("fmap", {}).items():
        for key, folder_name in fmap_data.items():
            folder_path = args.source / folder_name
            if not folder_path.exists():
                print(f"WARNING: folder not found: {folder_path}")
                continue
            niftis = find_nifti_files(folder_path)
            if not niftis:
                print(f"WARNING: no NIfTI in {folder_path}")
                continue

            if key == "PA":
                bids_suffix = "dir-PA_epi"
            elif key == "b1map":
                bids_suffix = "TB1map"
            else:
                bids_suffix = f"fmap-{key}"

            for nf in niftis:
                ext = ".nii.gz" if nf.name.endswith(".nii.gz") else ".nii"
                dst = (
                    args.dest
                    / f"sub-{subject}"
                    / ses_dir
                    / "fmap"
                    / build_dest_name(subject, session, bids_suffix, ext)
                )
                copy_file(nf, dst, args.method, args.dry)
            for jf in find_json_files(folder_path):
                dst = (
                    args.dest
                    / f"sub-{subject}"
                    / ses_dir
                    / "fmap"
                    / build_dest_name(subject, session, bids_suffix, ".json")
                )
                write_fmap_json_with_metadata(jf, dst, key, args.method, args.dry)


# -- Sessions map lookup -------------------------------------------------------


def lookup_session(sessions_map: Path, scanner_id: str) -> dict:
    """Return the sessions_map row for a given scanner pseudonym.

    Returns a dict with keys: participant_id, session_id, scanner_id, beh_id.
    Exits with an error message if the scanner_id is not found.
    """
    with sessions_map.open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("scanner_id", "").strip() == scanner_id.strip():
                return row
    sys.exit(f"Error: scanner_id '{scanner_id}' not found in {sessions_map}")


# -- CLI ----------------------------------------------------------------------


def _read_subject_csv(path: Path) -> list:
    """Read subject list CSV; utf-8-sig handles optional Excel BOM."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_participants_tsv(bids_root: Path, csv_rows: list) -> None:
    """Write/update participants.tsv in bids_root from CSV rows (age/sex default to n/a)."""
    tsv_path = bids_root / "participants.tsv"
    header = ["participant_id", "age", "sex"]
    existing: Dict[str, Any] = {}
    if tsv_path.exists():
        with tsv_path.open(newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                pid = row.get("participant_id", "").strip()
                if pid:
                    existing[pid] = row
    for row in csv_rows:
        bids_id = row.get("BIDS-ID", "").strip()
        if not bids_id:
            continue
        pid = f"sub-{bids_id.zfill(2)}"
        existing.setdefault(pid, {"participant_id": pid, "age": "n/a", "sex": "n/a"})
    bids_root.mkdir(parents=True, exist_ok=True)
    with tsv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for entry in sorted(existing.values(), key=lambda r: r["participant_id"]):
            w.writerow(entry)
    print(f"[OK]  participants.tsv updated ({len(existing)} subjects → {tsv_path})")


def main():  # noqa: C901
    p = argparse.ArgumentParser(
        description="Copy/link NIfTI series into a BIDS tree using a YAML mapping"
    )
    # Single-subject args (optional when --csv is used)
    p.add_argument("--source", type=Path, help="Source directory (single-subject mode)")
    p.add_argument(
        "--dest", required=True, type=Path, help="BIDS dataset root (created if absent)"
    )
    p.add_argument(
        "--config", type=Path, help="YAML or JSON mapping file (single-subject mode)"
    )
    p.add_argument(
        "--mode",
        choices=["files", "folders"],
        default="files",
        help="'files': flat *.nii.gz source (default); 'folders': one subfolder per series",
    )
    p.add_argument("--subject", help="Subject ID [default: basename of --source]")
    p.add_argument(
        "--session", default="01", help="Session label for BIDS filenames [01]"
    )
    p.add_argument("--method", choices=["copy", "link", "symlink"], default="copy")
    p.add_argument(
        "--events-dir", type=Path, help="[files] Folder with *_events.tsv files"
    )
    p.add_argument(
        "--dry", action="store_true", help="Dry-run: print actions without writing"
    )
    p.add_argument(
        "--sessions-map",
        type=Path,
        help="Path to code/sessions_map.tsv; resolves --subject/--session from --scanner-id",
    )
    p.add_argument(
        "--scanner-id",
        help="Scanner pseudonym (e.g. TYCM-RTYX); looked up in --sessions-map",
    )
    # CSV batch-mode args
    p.add_argument(
        "--csv", type=Path,
        help="[batch] Subject list CSV (columns: Pseudonym, BIDS-ID, ...)",
    )
    p.add_argument(
        "--source-base", type=Path,
        help="[batch] Base directory; per-subject source = <source-base>/<Pseudonym>/NIFTI/",
    )
    p.add_argument(
        "--config-dir", type=Path,
        help="[batch] Directory containing sub-{ID}_ses-{session}_mapping.yaml files",
    )
    args = p.parse_args()

    # --- Validate modes -------------------------------------------------------
    if args.csv and args.source:
        p.error("--csv and --source are mutually exclusive; use one or the other")
    if not args.csv and not args.source:
        p.error("one of --source or --csv is required")
    if args.csv and (not args.source_base or not args.config_dir):
        p.error("--source-base and --config-dir are required with --csv")
    if not args.csv and not args.config:
        p.error("--config is required without --csv")

    # --- Batch mode -----------------------------------------------------------
    if args.csv:
        import copy as _copy
        if not args.csv.is_file():
            sys.exit(f"CSV not found: {args.csv}")
        rows = _read_subject_csv(args.csv)
        session = args.session.removeprefix("ses-")
        ok = skipped = 0
        for row in rows:
            pseudonym = row.get("Pseudonym", "").strip()
            bids_id   = row.get("BIDS-ID", "").strip()
            if not pseudonym or not bids_id:
                print(f"[WARN] Row {row.get('Subject_NR','?')}: missing Pseudonym or BIDS-ID — skipping.")
                skipped += 1
                continue
            sub    = bids_id.zfill(2)
            source = args.source_base / pseudonym / "NIFTI"
            config = args.config_dir / f"sub-{sub}_ses-{session}_mapping.yaml"
            if not source.is_dir():
                print(f"[WARN] sub-{sub} ({pseudonym}): source not found: {source} — skipping.")
                skipped += 1
                continue
            if not config.is_file():
                print(f"[WARN] sub-{sub}: config not found: {config} — skipping.")
                skipped += 1
                continue
            mapping   = load_mapping(config)
            row_args  = _copy.copy(args)
            row_args.source = source
            print(f"\n--- sub-{sub} ({pseudonym}) ---")
            run_folders_mode(row_args, sub, session, mapping)
            ok += 1
        suffix = " (dry-run)" if args.dry else ""
        print(f"\nDone{suffix}: {ok}/{len(rows)} subjects processed, {skipped} skipped.")
        if not args.dry:
            _write_participants_tsv(args.dest, rows)
        return

    # --- Single-subject mode --------------------------------------------------
    if not args.source.is_dir():
        sys.exit(f"Source directory not found: {args.source}")
    if not args.config.is_file():
        sys.exit(f"Config file not found: {args.config}")
    if args.events_dir and not args.events_dir.is_dir():
        sys.exit(f"Events directory not found: {args.events_dir}")
    if args.sessions_map and not args.sessions_map.is_file():
        sys.exit(f"sessions_map not found: {args.sessions_map}")

    # Resolve subject/session from sessions_map when scanner_id is given
    if args.sessions_map and args.scanner_id:
        entry = lookup_session(args.sessions_map, args.scanner_id)
        if not args.subject:
            args.subject = entry["participant_id"]
        if args.session == "01":  # only override the default, not an explicit --session
            args.session = entry["session_id"]

    # Normalise subject / session (strip any sub-/ses- prefix users might add)
    subject = (args.subject or args.source.name).removeprefix("sub-")
    session = args.session.removeprefix("ses-")

    mapping = load_mapping(args.config)

    if args.mode == "files":
        run_files_mode(args, subject, session, mapping)
    else:
        run_folders_mode(args, subject, session, mapping)

    print("\n[OK] Done (dry-run)" if args.dry else "\n[OK] Finished copying/linking.")


if __name__ == "__main__":
    main()
