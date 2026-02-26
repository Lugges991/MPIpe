#!/usr/bin/env python3
"""generate_bids_config.py - Stage-1 helper that scans a folder of NIfTI (+JSON)
series, **guesses** how they should be organised in a BIDS tree, and emits a
YAML mapping for *copy2bids.py*.

* Accept both **.nii** and **.nii.gz** 
* **--force-task <NAME>** - label **all** detected BOLD runs with this task
  name, skipping the heuristic deduction completely.
* **--task-rename OLD=NEW** (older option) still works and is applied *after*
  --force-task (so you can force-task “fmri” then selectively rename runs if
  needed).

Typical runs
------------
Force every BOLD series to be task *vision*:

```bash
python generate_bids_config.py \
  --source /data/GCCP-KVKI/DICOM_NIFTI \
  --force-task vision \
  --out mapping.yaml
```

Rename an automatically-deduced “rest” task to “motor” while leaving others
untouched:

```bash
python generate_bids_config.py \
  --source /data/... \
  --task-rename rest=motor
```

Add `--no-prompt` to skip the confirmation question.
"""

import argparse
import itertools
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

try:
    import yaml  # pyyaml must be present for YAML I/O
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required - install with `pip install pyyaml`")

# Heuristic patterns - tweak if your scanner uses other naming conventions
GUESS_RULES = {
    "anat": {
        "T1w": re.compile(r"(?i)(T1|ADNI|MPRAGE)")
    },
    "func": {
        # Detects BOLD fMRI series. Task and run are parsed later.
        "bold": re.compile(r"(?i)(bold|ep3d|3DbSSFP)")
    },
    "fmap": {
        "gre": re.compile(r"(?i)(field|gre|revPE)")
    },
}
~
SKIP_PATTERNS = re.compile(r"(?i)(localizer|scout)")
SBREF_PAT = re.compile(r"SBRef", re.I)


def natural_sort_key(text: str):
    """Turn a string into a list of str|int for natural-order sorting."""
    return [int("".join(g)) if k else "".join(g) for k, g in itertools.groupby(text, str.isdigit)]


def scan_source(source: Path) -> List[Path]:
    """Return *.nii* and *.nii.gz* paths sorted alphanumerically."""
    return sorted(
        itertools.chain(source.glob("*.nii"), source.glob("*.nii.gz")),
        key=lambda p: natural_sort_key(p.name),
    )


def series_id(p: Path) -> str:
    """Return the filename stem without .nii or .nii.gz extension."""
    if p.suffix == ".gz" and p.name.endswith(".nii.gz"):
        return p.name[:-7]
    return p.stem


def categorise(fpaths: List[Path], force_task: str | None = None) -> Dict:
    """Apply regex heuristics and build mapping dict."""
    mapping: Dict[str, Dict] = defaultdict(dict)  # type: ignore
    run_counters: Dict[str, int] = defaultdict(int)
    pending_sbref: tuple[str, str] | None = None  # (stem, fname)

    for f in fpaths:
        fname = f.name
        sid = series_id(f)

        if SKIP_PATTERNS.search(fname):
            continue  # ignore scouts/localisers

        # SBRef 
        if SBREF_PAT.search(fname):
            pending_sbref = (sid, fname)
            continue

        matched = False

        # anatomical
        for label, pat in GUESS_RULES["anat"].items():
            if pat.search(fname):
                mapping.setdefault("anat", {}).setdefault(label, []).append(sid)
                matched = True
                break
        if matched:
            continue

        # functional  
        if GUESS_RULES["func"]["bold"].search(fname):
            # Decide task label
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
            mapping.setdefault("func", {}).setdefault(task, {})[run_label] = {
                "bold": sid,
            }
            if pending_sbref:
                mapping["func"][task][run_label]["sbref"] = pending_sbref[0]
                pending_sbref = None
            matched = True
            continue

        # fieldmaps
        for fmap_type, pat in GUESS_RULES["fmap"].items():
            if pat.search(fname):
                if re.search(r"e1", fname, re.I):
                    key = "magnitude1"
                elif re.search(r"ph|phase", fname, re.I):
                    key = "phase2"
                else:
                    key = "phase1"
                mapping.setdefault("fmap", {}).setdefault(fmap_type, {})[key] = sid
                matched = True
                break
        if matched:
            continue

    return mapping

def parse_task_renames(pairs: List[str] | None) -> Dict[str, str]:
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
            print(f"⚠  task '{old}' not in auto-mapping; rename ignored.")
            continue
        if new in mapping["func"]:
            print(f"⚠  target task name '{new}' already exists - merge aborted for '{old}'.")
            continue
        mapping["func"][new] = mapping["func"].pop(old)

def main():  # noqa: C901
    p = argparse.ArgumentParser(description="Generate YAML mapping for copy2bids.py (single-session studies)")
    p.add_argument("--source", required=True, type=Path, help="Folder with NIfTI series (.nii / .nii.gz) + JSON sidecars")
    p.add_argument("--out", type=Path, default=Path("mapping.yaml"), help="YAML file to write [mapping.yaml]")
    p.add_argument("--no-prompt", action="store_true", help="Write without confirmation prompt")
    p.add_argument("--force-task", help="Assign *all* BOLD series to this task label (overrides heuristics)")
    p.add_argument("--task-rename", "-t", action="append", metavar="OLD=NEW", help="Rename task OLD to NEW in the mapping (may be repeated)")
    args = p.parse_args()

    if not args.source.is_dir():
        sys.exit(f"Source directory not found: {args.source}")

    mapping = categorise(scan_source(args.source), force_task=args.force_task)

    # Apply any user-requested task renames (after force-task, if any)
    renames = parse_task_renames(args.task_rename)
    apply_task_renames(mapping, renames)

    yaml_str = yaml.safe_dump(dict(mapping), sort_keys=False)

    print("\nProposed mapping (edit later if needed):\n")
    print(yaml_str)

    if not args.no_prompt:
        ans = input(f"Write mapping to {args.out.resolve()}? [Y/n] ")
        if ans.strip().lower() not in ("", "y", "yes"):
            print("Aborted - no file written.")
            sys.exit(0)

    args.out.write_text(yaml_str)
    print(f"\n✔ Mapping saved to {args.out.resolve()}.\n   Review/edit if necessary, then run copy2bids.py --config {args.out}\n")


if __name__ == "__main__":
    main()
