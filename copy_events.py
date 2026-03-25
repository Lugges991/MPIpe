#!/usr/bin/env python3
"""copy_events.py - Copy FSL/BIDS events TSV files into a BIDS func/ tree.

Source layout
-------------
    <events-base>/sub-{Subject_NR}/events/
        s{NR}r{NN}{cond}_events.tsv
        s{NR}r{NN}{cond}_switch_events.tsv

where {NR} is the Subject_NR from the subject CSV, {NN} is the run number, and
{cond} is 'r' (report) or 'nr' (no-report).

Not every source run has a corresponding MRI acquisition (training / calibration
runs have events files but no NIfTI).  The mapping config (events_config.yaml)
lists only the runs to copy and maps each source run number to a BIDS run number.

BIDS output
-----------
    <dest>/sub-{BIDS-ID}/ses-{session}/func/
        sub-{ID}_ses-{session}_task-{task}_acq-report_run-{N}_events.tsv
        sub-{ID}_ses-{session}_task-{task}_acq-noreport_run-{N}_events.tsv
        sub-{ID}_ses-{session}_task-{task}_acq-report_run-{N}_switch_events.tsv
        ...

Usage
-----
    python copy_events.py \\
        --csv NRBR_subject_list.csv \\
        --events-base /path/to/BRET/data \\
        --config events_config.yaml \\
        --dest /data/BIDS \\
        --session 01 --dry
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required - install with `pip install pyyaml`")

# Re-use copy_file from copy2bids so method/dry-run behaviour is identical.
from copy2bids import copy_file


# -- Helpers ------------------------------------------------------------------


def parse_events_filename(fname: str) -> Optional[Dict]:
    """Parse a source events filename into its components.

    Accepted patterns:
        s{NR}r{NN}nr_events.tsv
        s{NR}r{NN}r_events.tsv
        s{NR}r{NN}nr_switch_events.tsv
        s{NR}r{NN}r_switch_events.tsv

    Returns a dict with keys: subject_nr, run_num, cond, is_switch.
    Returns None if the filename does not match.
    """
    m = re.match(r"s(\d+)r(\d+)(nr|r)(_switch)?_events\.tsv$", fname)
    if not m:
        return None
    return {
        "subject_nr": m.group(1),
        "run_num":    m.group(2),                                    # e.g. "04"
        "cond":       "noreport" if m.group(3) == "nr" else "report",
        "is_switch":  m.group(4) is not None,
    }


def build_bids_events_name(
    subject: str, session: str, task: str, acq: str, run: str, is_switch: bool
) -> str:
    run_label = f"run-{int(run):02d}"
    suffix    = "switch_events" if is_switch else "events"
    return f"sub-{subject}_ses-{session}_task-{task}_acq-{acq}_{run_label}_{suffix}.tsv"


def read_subject_csv(path: Path) -> Dict[str, str]:
    """Return {Subject_NR: BIDS-ID (zero-padded)} from the subject list CSV."""
    mapping: Dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            nr     = row.get("Subject_NR", "").strip()
            bids   = row.get("BIDS-ID", "").strip()
            if nr and bids:
                mapping[nr] = bids.zfill(2)
    return mapping


def load_config(path: Path) -> Dict:
    """Load the events YAML config (task name + run mapping)."""
    with path.open() as f:
        cfg = yaml.safe_load(f)
    if "task" not in cfg or "runs" not in cfg:
        sys.exit(f"Config must contain 'task' and 'runs' keys: {path}")
    # Normalise all run keys to strings
    cfg["runs"] = {str(k): str(v) for k, v in cfg["runs"].items()}
    return cfg


# -- Main ---------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(
        description="Copy FSL/BIDS events TSV files into a BIDS func/ tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--csv", required=True, type=Path,
                   help="Subject list CSV (columns: Subject_NR, BIDS-ID, …)")
    p.add_argument("--events-base", required=True, type=Path,
                   help="Root of events tree; per-subject path: <base>/sub-{NR}/events/")
    p.add_argument("--config", required=True, type=Path,
                   help="YAML run-mapping config (task name + source→BIDS run numbers)")
    p.add_argument("--dest", required=True, type=Path,
                   help="BIDS root directory")
    p.add_argument("--session", default="01",
                   help="Session label for BIDS filenames [01]")
    p.add_argument("--method", choices=["copy", "link", "symlink"], default="copy",
                   help="File transfer method [copy]")
    p.add_argument("--dry", action="store_true",
                   help="Print actions without writing any files")
    args = p.parse_args()

    if not args.csv.is_file():
        sys.exit(f"CSV not found: {args.csv}")
    if not args.config.is_file():
        sys.exit(f"Config not found: {args.config}")
    if not args.events_base.is_dir():
        sys.exit(f"Events base directory not found: {args.events_base}")

    session     = args.session.removeprefix("ses-")
    nr_to_bids  = read_subject_csv(args.csv)
    cfg         = load_config(args.config)
    task        = cfg["task"]
    run_map     = cfg["runs"]   # {"04": "01", ...}

    total_copied = total_skipped = 0

    for subject_nr, bids_id in sorted(nr_to_bids.items(), key=lambda x: x[1]):
        events_dir = args.events_base / f"sub-{subject_nr}" / "events"
        if not events_dir.is_dir():
            print(f"[WARN] sub-{bids_id} (NR={subject_nr}): events dir not found: {events_dir} — skipping.")
            total_skipped += 1
            continue

        tsv_files = sorted(events_dir.glob("*.tsv"))
        if not tsv_files:
            print(f"[WARN] sub-{bids_id} (NR={subject_nr}): no .tsv files in {events_dir} — skipping.")
            total_skipped += 1
            continue

        copied = 0
        for src in tsv_files:
            parsed = parse_events_filename(src.name)
            if parsed is None:
                continue  # not an events file matching the expected pattern
            if parsed["run_num"] not in run_map:
                continue  # training / calibration run — not in config

            bids_run  = run_map[parsed["run_num"]]
            dst_name  = build_bids_events_name(
                bids_id, session, task, parsed["cond"], bids_run, parsed["is_switch"]
            )
            dst = args.dest / f"sub-{bids_id}" / f"ses-{session}" / "func" / dst_name
            copy_file(src, dst, args.method, args.dry)
            copied += 1

        if copied:
            print(f"[OK]  sub-{bids_id} (NR={subject_nr}): {copied} events files {'would be ' if args.dry else ''}copied.")
        else:
            print(f"[WARN] sub-{bids_id} (NR={subject_nr}): no events files matched the config runs.")
            total_skipped += 1
            continue
        total_copied += 1

    suffix = " (dry-run)" if args.dry else ""
    print(f"\nDone{suffix}: {total_copied} subjects processed, {total_skipped} skipped.")


if __name__ == "__main__":
    main()
