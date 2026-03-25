#!/usr/bin/env python3
"""generate_bids_config.py - Stage-1 helper that scans a folder of NIfTI (+JSON)
series (or subdirectories), guesses how they should be organised in a BIDS tree,
and emits a YAML mapping for copy2bids.py.

Two modes
---------
files (default)
    Scans *.nii / *.nii.gz directly in --source.
    Produces a flat mapping (no session wrapper).
    Detects: T1w, BOLD (+SBRef), GRE fieldmaps.

folders
    Scans immediate subdirectories of --source (one folder per series).
    Deduplicates folders with the same name suffix (keeps highest prefix number).
    Test runs / scouts are automatically skipped.
    Produces a session-wrapped mapping  (ses-{session}: ...).
    Detects: T1w (MPRAGE), EPI bold, bSSFP bold, reversed-PE fieldmaps, B1 maps.

Usage examples
--------------
# files mode (original single-session workflow)
python generate_bids_config.py \\
  --source /data/NIFTI \\
  --force-task vision \\
  --out mapping.yaml

# folders mode (multi-sequence / multi-run workflow)
python generate_bids_config.py \\
  --source /data/studies/116/NIFTI \\
  --mode folders \\
  --task prf \\
  --session 01 \\
  --out mapping.yaml
"""

import argparse
import csv
import itertools
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml  # pyyaml must be present for YAML I/O
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required - install with `pip install pyyaml`")

# -- Heuristic patterns -------------------------------------------------------

# files mode
RULES_FILES = {
    "anat": {
        "T1w": re.compile(r"(?i)(T1|ADNI|MPRAGE)"),
    },
    "func": {
        "bold": re.compile(r"(?i)(bold|ep3d|3DbSSFP)"),
    },
    "fmap": {
        "gre": re.compile(r"(?i)(field|gre|revPE)"),
    },
}

# folders mode
RULES_FOLDERS = {
    "anat": {
        "T1w": re.compile(r"(?i)(MPRAGE|T1|ADNI|anatomical)"),
    },
    "func": {
        "epi":   re.compile(r"(?i)(ep3d|epi|bold)"),
        "bssfp": re.compile(r"(?i)(3DbSSFP|bssfp|ssfp)"),
    },
    "fmap": {
        "epi_rev": re.compile(r"(?i)(revPE|reversed|topup|\bPA\b)"),
        "b1map":   re.compile(r"(?i)b1map"),
        "gre":     re.compile(r"(?i)(gre_field|field_map)"),
    },
}

SKIP_FILES   = re.compile(r"(?i)(localizer|scout)")
SKIP_FOLDERS = re.compile(r"(?i)(localizer|scout|B0_Map|aa_B0Mapping|replaced_|test)")
SBREF_FOLDERS = re.compile(r"SBRef", re.I)
SBREF_PAT    = re.compile(r"SBRef", re.I)

# -- Utilities ----------------------------------------------------------------

def natural_sort_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def series_id(p: Path) -> str:
    """Filename stem without .nii or .nii.gz."""
    if p.suffix == ".gz" and p.name.endswith(".nii.gz"):
        return p.name[:-7]
    return p.stem

# -- files mode ---------------------------------------------------------------

def scan_files(source: Path) -> List[Path]:
    """Return *.nii* paths sorted alphanumerically."""
    return sorted(
        itertools.chain(source.glob("*.nii"), source.glob("*.nii.gz")),
        key=lambda p: natural_sort_key(p.name),
    )


def categorise_files(fpaths: List[Path], force_task: Optional[str] = None) -> Dict:
    """Apply regex heuristics on flat NIfTI files and build mapping dict."""
    mapping: Dict = defaultdict(dict)
    run_counters: Dict[str, int] = defaultdict(int)
    pending_sbref: Optional[tuple] = None

    for f in fpaths:
        fname = f.name
        sid = series_id(f)

        if SKIP_FILES.search(fname):
            continue

        if SBREF_PAT.search(fname):
            pending_sbref = (sid, fname)
            continue

        matched = False

        # anatomical
        for label, pat in RULES_FILES["anat"].items():
            if pat.search(fname):
                mapping.setdefault("anat", {}).setdefault(label, []).append(sid)
                matched = True
                break
        if matched:
            continue

        # functional
        if RULES_FILES["func"]["bold"].search(fname):
            if force_task:
                task = force_task.lower()
            else:
                tokens = fname.split("_")
                try:
                    task_token = next(t for t in tokens if t.lower().startswith("task"))
                    task = task_token.split("-", 1)[1]
                except StopIteration:
                    pre_bold = tokens[tokens.index(next(t for t in tokens if "bold" in t.lower())) - 1]
                    task = pre_bold or "task"
                task = task.lower()

            run_counters[task] += 1
            run_label = f"run-{run_counters[task]:02d}"
            mapping.setdefault("func", {}).setdefault(task, {})[run_label] = {"bold": sid}
            if pending_sbref:
                mapping["func"][task][run_label]["sbref"] = pending_sbref[0]
                pending_sbref = None
            continue

        # fieldmaps
        for fmap_type, pat in RULES_FILES["fmap"].items():
            if pat.search(fname):
                if re.search(r"e1", fname, re.I):
                    key = "magnitude1"
                elif re.search(r"ph|phase", fname, re.I):
                    key = "phase2"
                else:
                    key = "phase1"
                mapping.setdefault("fmap", {}).setdefault(fmap_type, {})[key] = sid
                break

    return mapping


def parse_task_renames(pairs: Optional[List[str]]) -> Dict[str, str]:
    renames: Dict[str, str] = {}
    if not pairs:
        return renames
    for item in pairs:
        if "=" not in item:
            sys.exit(f"--task-rename expects OLD=NEW format, got: {item}")
        old, new = item.split("=", 1)
        if not old or not new:
            sys.exit(f"Invalid rename pair: {item}")
        renames[old.lower()] = new
    return renames


def apply_task_renames(mapping: Dict, renames: Dict[str, str]):
    if not renames or "func" not in mapping:
        return
    for old, new in list(renames.items()):
        if old not in mapping["func"]:
            print(f"Warning: task '{old}' not in mapping; rename ignored.")
            continue
        if new in mapping["func"]:
            print(f"Warning: target task name '{new}' already exists - merge aborted for '{old}'.")
            continue
        mapping["func"][new] = mapping["func"].pop(old)

# -- folders mode -------------------------------------------------------------

def deduplicate_folders(folders: List[Path]) -> List[Path]:
    """Keep only the folder with the highest numeric prefix per unique name suffix."""
    groups: Dict[str, List[Path]] = defaultdict(list)
    for folder in folders:
        parts = folder.name.split("_", 1)
        suffix = parts[1] if len(parts) > 1 else folder.name
        groups[suffix].append(folder)

    result: List[Path] = []
    for suffix, group in groups.items():
        if len(group) == 1:
            result.extend(group)
        else:
            def prefix_num(p: Path) -> int:
                m = re.match(r"^(\d+)", p.name)
                return int(m.group(1)) if m else 0

            best = max(group, key=prefix_num)
            print(f"Duplicate suffix '{suffix}': {[p.name for p in group]} -> keeping {best.name}")
            result.append(best)
    return result


def scan_folders(source: Path, dedup: bool = False) -> List[Path]:
    """Return immediate subdirectories sorted naturally."""
    folders = [p for p in source.iterdir() if p.is_dir()]
    if dedup:
        folders = deduplicate_folders(folders)
    return sorted(folders, key=lambda p: natural_sort_key(p.name))


def categorise_folders(folders: List[Path], task_name: str = "task", session_id: str = "01") -> Dict:
    """Apply heuristics on folder names and build session-wrapped mapping dict."""
    ses_key = f"ses-{session_id}"
    mapping: Dict = {ses_key: {}}
    epi_run = bssfp_run = 0

    gre_run = 0
    for folder in folders:
        name = folder.name

        if SKIP_FOLDERS.search(name):
            continue

        if SBREF_FOLDERS.search(name):
            continue

        # anatomical
        if RULES_FOLDERS["anat"]["T1w"].search(name):
            mapping[ses_key].setdefault("anat", {}).setdefault("T1w", []).append(name)
            continue

        # fieldmaps (check before func to prevent revPE matching as EPI)
        if RULES_FOLDERS["fmap"]["epi_rev"].search(name):
            mapping[ses_key].setdefault("fmap", {}).setdefault("dir", {})["PA"] = name
            continue
        if RULES_FOLDERS["fmap"]["b1map"].search(name):
            mapping[ses_key].setdefault("fmap", {}).setdefault("dir", {})["b1map"] = name
            continue
        if RULES_FOLDERS["fmap"]["gre"].search(name):
            gre_run += 1
            key = f"e{gre_run}"
            mapping[ses_key].setdefault("fmap", {}).setdefault("gre", {})[key] = name
            continue

        # functional - bSSFP before EPI to avoid broad EPI pattern stealing bSSFP series
        if RULES_FOLDERS["func"]["bssfp"].search(name):
            bssfp_run += 1
            run_label = f"run-{bssfp_run:02d}"
            mapping[ses_key].setdefault("func", {}).setdefault(task_name, {}).setdefault(run_label, {})["bssfp"] = name
            continue
        if RULES_FOLDERS["func"]["epi"].search(name):
            epi_run += 1
            run_label = f"run-{epi_run:02d}"
            mapping[ses_key].setdefault("func", {}).setdefault(task_name, {}).setdefault(run_label, {})["epi"] = name
            continue

    return mapping

# -- CSV batch helper ----------------------------------------------------------

def read_subject_csv(path: Path) -> List[Dict]:
    """Read subject list CSV; utf-8-sig handles optional Excel BOM."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# -- CLI ----------------------------------------------------------------------

def main():  # noqa: C901
    p = argparse.ArgumentParser(
        description="Generate YAML mapping for copy2bids.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Single-subject source (mutually exclusive with --csv)
    p.add_argument("--source", type=Path, help="Source directory (single-subject mode)")
    p.add_argument("--out", type=Path, default=Path("mapping.yaml"), help="Output YAML file [mapping.yaml]")
    p.add_argument("--mode", choices=["files", "folders"], default="files",
                   help="'files': scan *.nii* directly (default); 'folders': scan subdirectories")
    p.add_argument("--no-prompt", action="store_true", help="Write without confirmation prompt")
    # files-mode options
    p.add_argument("--force-task", help="[files] Assign all BOLD runs to this task label")
    p.add_argument("--task-rename", "-t", action="append", metavar="OLD=NEW",
                   help="[files] Rename task OLD->NEW in the mapping (repeatable)")
    # folders-mode options
    p.add_argument("--task", default="task", help="[folders] Task name for functional data [task]")
    p.add_argument("--session", default="01", help="[folders] Session ID used as mapping key [01]")
    p.add_argument("--dedup", action="store_true",
                   help="[folders] Deduplicate: keep only the highest-numbered folder per name suffix (for aborted+repeated scans)")
    p.add_argument("--subject",
                   help="[folders] BIDS subject label (without sub-); used with --out-dir for auto-naming")
    p.add_argument("--out-dir", type=Path,
                   help="[folders] Write to <out-dir>/sub-{subject}_ses-{session}_mapping.yaml (overrides --out)")
    # CSV batch-mode options
    p.add_argument("--csv", type=Path,
                   help="[batch] Subject list CSV (columns: Pseudonym, BIDS-ID, Comments, ...)")
    p.add_argument("--source-base", type=Path,
                   help="[batch] Base directory; per-subject source = <source-base>/<Pseudonym>/NIFTI/")
    args = p.parse_args()

    # --- Validate mutually exclusive modes ------------------------------------
    if args.csv and args.source:
        p.error("--csv and --source are mutually exclusive; use one or the other")
    if not args.csv and not args.source:
        p.error("one of --source or --csv is required")
    if args.csv and not args.source_base:
        p.error("--source-base is required with --csv")
    if args.csv and not args.out_dir:
        p.error("--out-dir is required with --csv")

    # --- Batch mode -----------------------------------------------------------
    if args.csv:
        if not args.csv.is_file():
            sys.exit(f"CSV not found: {args.csv}")
        rows = read_subject_csv(args.csv)
        ok = skipped = 0
        for row in rows:
            pseudonym = row.get("Pseudonym", "").strip()
            bids_id   = row.get("BIDS-ID", "").strip()
            if not pseudonym or not bids_id:
                print(f"[WARN] Row {row.get('Subject_NR','?')}: missing Pseudonym or BIDS-ID — skipping.")
                skipped += 1
                continue
            source = args.source_base / pseudonym / "NIFTI"
            if not source.is_dir():
                print(f"[WARN] sub-{bids_id} ({pseudonym}): source not found: {source} — skipping.")
                skipped += 1
                continue
            sub = bids_id.zfill(2)
            ses = args.session.removeprefix("ses-")
            mapping = categorise_folders(
                scan_folders(source, dedup=args.dedup),
                task_name=args.task,
                session_id=ses,
            )
            yaml_str = yaml.safe_dump(dict(mapping), sort_keys=False, default_flow_style=False)
            out_path = args.out_dir / f"sub-{sub}_ses-{ses}_mapping.yaml"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(yaml_str)
            comment = row.get("Comments", "").strip()
            note    = f"  [NOTE: {comment}]" if comment else ""
            print(f"[OK]  {out_path}{note}")
            ok += 1
        print(f"\nDone: {ok}/{len(rows)} configs written, {skipped} skipped.")
        return

    # --- Single-subject mode --------------------------------------------------
    if not args.source.is_dir():
        sys.exit(f"Source directory not found: {args.source}")

    if args.mode == "files":
        mapping = categorise_files(scan_files(args.source), force_task=args.force_task)
        renames = parse_task_renames(args.task_rename)
        apply_task_renames(mapping, renames)
        mode_label = "files"
    else:
        mapping = categorise_folders(scan_folders(args.source, dedup=args.dedup), task_name=args.task, session_id=args.session)
        mode_label = f"folders (ses-{args.session}, task: {args.task})"

    yaml_str = yaml.safe_dump(dict(mapping), sort_keys=False, default_flow_style=False)

    print(f"\nProposed mapping [{mode_label}]:\n")
    print(yaml_str)

    # Resolve output path
    if args.out_dir and args.subject:
        sub = args.subject.removeprefix("sub-")
        ses = args.session.removeprefix("ses-")
        out_path = args.out_dir / f"sub-{sub}_ses-{ses}_mapping.yaml"
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = args.out

    if not args.no_prompt:
        ans = input(f"Write mapping to {out_path.resolve()}? [Y/n] ")
        if ans.strip().lower() not in ("", "y", "yes"):
            print("Aborted - no file written.")
            sys.exit(0)

    out_path.write_text(yaml_str)
    print(f"\n[OK] Mapping saved to {out_path.resolve()}.\n   Review/edit if necessary, then run copy2bids.py --config {out_path}\n")


if __name__ == "__main__":
    main()
