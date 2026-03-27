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

Usage (new — per-subject configs)
----------------------------------
    python copy_events.py \\
        --config-dir .data/events_configs \\
        --events-base ../BRET/data \\
        --dest /data/BIDS --dry

Usage (legacy — global config + CSV)
--------------------------------------
    python copy_events.py \\
        --csv .data/subject_map.csv \\
        --events-base ../BRET/data \\
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
        "run_num": m.group(2),  # e.g. "04"
        "cond": "noreport" if m.group(3) == "nr" else "report",
        "is_switch": m.group(4) is not None,
    }


def build_bids_events_name(
    subject: str, session: str, task: str, acq: str, run: str, is_switch: bool
) -> str:
    run_label = f"run-{int(run):02d}"
    suffix = "switch_events" if is_switch else "events"
    return f"sub-{subject}_ses-{session}_task-{task}_acq-{acq}_{run_label}_{suffix}.tsv"


def read_subject_csv(path: Path) -> Dict[str, str]:
    """Return {Subject_NR: BIDS-ID (zero-padded)} from the subject list CSV."""
    mapping: Dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            nr = row.get("Subject_NR", "").strip()
            bids = row.get("BIDS-ID", "").strip()
            if nr and bids:
                mapping[nr] = bids.zfill(2)
    return mapping


def load_config(path: Path) -> Dict:
    """Load a global events YAML config (task name + run mapping)."""
    with path.open() as f:
        cfg = yaml.safe_load(f)
    if "task" not in cfg or "runs" not in cfg:
        sys.exit(f"Config must contain 'task' and 'runs' keys: {path}")
    # Normalise all run keys to strings
    cfg["runs"] = {str(k): str(v) for k, v in cfg["runs"].items()}
    return cfg


def load_per_subject_config(path: Path) -> Dict:
    """Load and validate a per-subject events config YAML."""
    with path.open() as f:
        cfg = yaml.safe_load(f)
    required = ("subject_nr", "bids_id", "session", "task", "runs")
    missing = [k for k in required if k not in cfg]
    if missing:
        sys.exit(f"Per-subject config {path} is missing keys: {missing}")
    cfg["runs"] = {str(k): str(v) for k, v in cfg["runs"].items()}
    cfg["subject_nr"] = str(cfg["subject_nr"])
    cfg["bids_id"] = str(cfg["bids_id"]).zfill(2)
    cfg["session"] = str(cfg["session"]).removeprefix("ses-")
    return cfg


def process_subject(
    subject_nr: str,
    bids_id: str,
    session: str,
    task: str,
    run_map: Dict[str, str],
    events_base: Path,
    dest: Path,
    method: str,
    dry: bool,
) -> int:
    """Copy events for one subject. Returns number of files copied (0 = skipped)."""
    events_dir = events_base / f"sub-{subject_nr}" / "events"
    tag = f"sub-{bids_id} (NR={subject_nr})"

    if not events_dir.is_dir():
        print(f"[WARN] {tag}: events dir not found: {events_dir} — skipping.")
        return 0

    tsv_files = sorted(events_dir.glob("*.tsv"))
    if not tsv_files:
        print(f"[WARN] {tag}: no .tsv files in {events_dir} — skipping.")
        return 0

    copied = 0
    for src in tsv_files:
        parsed = parse_events_filename(src.name)
        if parsed is None:
            continue
        if parsed["run_num"] not in run_map:
            continue  # training / calibration run — not in config

        bids_run = run_map[parsed["run_num"]]
        dst_name = build_bids_events_name(
            bids_id, session, task, parsed["cond"], bids_run, parsed["is_switch"]
        )
        dst = dest / f"sub-{bids_id}" / f"ses-{session}" / "func" / dst_name
        copy_file(src, dst, method, dry)
        copied += 1

    if copied:
        print(
            f"[OK]  {tag}: {copied} events files {'would be ' if dry else ''}copied."
        )
    else:
        print(f"[WARN] {tag}: no events files matched the config runs.")
    return copied


# -- Main ---------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(
        description="Copy FSL/BIDS events TSV files into a BIDS func/ tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- Mode A: per-subject config directory (new) ---
    p.add_argument(
        "--config-dir",
        type=Path,
        help="Directory of per-subject events config YAMLs (from generate_events_config.py)",
    )

    # --- Mode B: global config + CSV (legacy) ---
    p.add_argument(
        "--csv",
        type=Path,
        help="[legacy] Subject list CSV (columns: Subject_NR, BIDS-ID, …)",
    )
    p.add_argument(
        "--config",
        type=Path,
        help="[legacy] Global YAML run-mapping config (task + source→BIDS run numbers)",
    )

    # --- Common args ---
    p.add_argument(
        "--events-base",
        required=True,
        type=Path,
        help="Root of events tree; per-subject path: <base>/sub-{NR}/events/",
    )
    p.add_argument("--dest", required=True, type=Path, help="BIDS root directory")
    p.add_argument(
        "--session", default="01", help="[legacy] Session label for BIDS filenames [01]"
    )
    p.add_argument(
        "--method",
        choices=["copy", "link", "symlink"],
        default="copy",
        help="File transfer method [copy]",
    )
    p.add_argument(
        "--dry", action="store_true", help="Print actions without writing any files"
    )
    args = p.parse_args()

    # --- Validate mode ---
    if args.config_dir and (args.csv or args.config):
        p.error("--config-dir is mutually exclusive with --csv / --config")
    if not args.config_dir and not (args.csv and args.config):
        p.error("Provide either --config-dir or both --csv and --config")

    if not args.events_base.is_dir():
        sys.exit(f"Events base directory not found: {args.events_base}")

    total_copied = total_skipped = 0

    # ------------------------------------------------------------------ new mode
    if args.config_dir:
        if not args.config_dir.is_dir():
            sys.exit(f"Config directory not found: {args.config_dir}")
        config_files = sorted(args.config_dir.glob("*_events_config.yaml"))
        if not config_files:
            sys.exit(f"No *_events_config.yaml files found in {args.config_dir}")

        for cfg_path in config_files:
            cfg = load_per_subject_config(cfg_path)
            n = process_subject(
                subject_nr=cfg["subject_nr"],
                bids_id=cfg["bids_id"],
                session=cfg["session"],
                task=cfg["task"],
                run_map=cfg["runs"],
                events_base=args.events_base,
                dest=args.dest,
                method=args.method,
                dry=args.dry,
            )
            if n:
                total_copied += 1
            else:
                total_skipped += 1

    # ---------------------------------------------------------------- legacy mode
    else:
        if not args.csv.is_file():
            sys.exit(f"CSV not found: {args.csv}")
        if not args.config.is_file():
            sys.exit(f"Config not found: {args.config}")

        session = args.session.removeprefix("ses-")
        nr_to_bids = read_subject_csv(args.csv)
        cfg = load_config(args.config)
        task = cfg["task"]
        run_map = cfg["runs"]

        for subject_nr, bids_id in sorted(nr_to_bids.items(), key=lambda x: x[1]):
            n = process_subject(
                subject_nr=subject_nr,
                bids_id=bids_id,
                session=session,
                task=task,
                run_map=run_map,
                events_base=args.events_base,
                dest=args.dest,
                method=args.method,
                dry=args.dry,
            )
            if n:
                total_copied += 1
            else:
                total_skipped += 1

    suffix = " (dry-run)" if args.dry else ""
    print(
        f"\nDone{suffix}: {total_copied} subjects processed, {total_skipped} skipped."
    )


if __name__ == "__main__":
    main()
