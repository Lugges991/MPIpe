#!/usr/bin/env python3
"""generate_events_config.py - Derive per-subject events run-mapping configs.

For each subject in the CSV, this script:
  1. Reads the subject's BIDS mapping YAML to count how many functional runs
     were acquired.
  2. Scans the subject's events directory, collects unique source run numbers,
     sorts them numerically.
  3. Takes the *last N* source runs (N = number of BIDS runs), discarding
     training/calibration runs at the beginning.
  4. Writes a per-subject events config YAML that the user can review and
     correct before running copy_events.py.

Usage
-----
    python generate_events_config.py \\
        --csv .data/subject_map.csv \\
        --mappings-dir .data/mappings \\
        --events-base ../BRET/data \\
        --task nrbr \\
        --session 01 \\
        --out-dir .data/events_configs

After generation, inspect / edit the configs in --out-dir, then run:

    python copy_events.py \\
        --config-dir .data/events_configs \\
        --events-base ../BRET/data \\
        --dest /data/BIDS --dry
"""

import argparse
import csv
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required — install with `pip install pyyaml`")

# Force single-quote style for all strings so run numbers like 08/09 are
# always quoted and remain strings when the file is read back.
yaml.add_representer(
    str,
    lambda dumper, data: dumper.represent_scalar(
        "tag:yaml.org,2002:str", data, style="'"
    ),
)

from copy_events import parse_events_filename


# ---------------------------------------------------------------------------

def read_subject_csv(path: Path):
    """Return list of dicts from CSV; rows with 'DISCARD' in Comments are flagged."""
    subjects = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            nr = row.get("Subject_NR", "").strip()
            bids = row.get("BIDS-ID", "").strip()
            comment = row.get("Comments", "").strip()
            if not nr or not bids:
                continue
            subjects.append({
                "subject_nr": nr,
                "bids_id": bids.zfill(2),
                "discard": "discard" in comment.lower(),
                "comment": comment,
            })
    return subjects


def count_func_runs(mapping_path: Path, session: str):
    """Return (N_runs, task_key) from a mapping YAML, or (None, None) on error."""
    with mapping_path.open() as f:
        data = yaml.safe_load(f)
    ses_key = f"ses-{session}"
    func = (data or {}).get(ses_key, {}).get("func", {})
    if not func:
        return None, None
    task_key = next(iter(func))
    runs = func[task_key]
    n = sum(1 for k in runs if k.startswith("run-"))
    return n, task_key


def collect_source_runs(events_dir: Path, subject_nr: str):
    """Return sorted list of unique source run number strings found in events_dir."""
    run_nums = set()
    for f in events_dir.glob("*.tsv"):
        parsed = parse_events_filename(f.name)
        if parsed and parsed["subject_nr"] == subject_nr:
            run_nums.add(parsed["run_num"])
    return sorted(run_nums, key=lambda x: int(x))


# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(
        description="Generate per-subject events run-mapping configs from BIDS mapping YAMLs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--csv", required=True, type=Path,
        help="Subject list CSV (columns: Subject_NR, BIDS-ID, Comments, …)",
    )
    p.add_argument(
        "--mappings-dir", required=True, type=Path,
        help="Directory of BIDS mapping YAMLs (sub-{ID}_ses-{session}_mapping.yaml)",
    )
    p.add_argument(
        "--events-base", required=True, type=Path,
        help="Root of events tree; per-subject path: <base>/sub-{NR}/events/",
    )
    p.add_argument(
        "--task", required=True,
        help="BIDS task label for events filenames (e.g. nrbr)",
    )
    p.add_argument(
        "--session", default="01",
        help="Session label [01]",
    )
    p.add_argument(
        "--out-dir", required=True, type=Path,
        help="Directory to write per-subject events config YAMLs",
    )
    args = p.parse_args()

    if not args.csv.is_file():
        sys.exit(f"CSV not found: {args.csv}")
    if not args.mappings_dir.is_dir():
        sys.exit(f"Mappings directory not found: {args.mappings_dir}")
    if not args.events_base.is_dir():
        sys.exit(f"Events base directory not found: {args.events_base}")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    session = args.session.removeprefix("ses-")
    subjects = read_subject_csv(args.csv)

    written = skipped = 0

    for subj in subjects:
        nr = subj["subject_nr"]
        bids_id = subj["bids_id"]
        tag = f"sub-{bids_id} (NR={nr})"

        if subj["discard"]:
            print(f"[SKIP] {tag}: marked DISCARD — {subj['comment']}")
            skipped += 1
            continue

        # --- BIDS mapping YAML ---
        mapping_path = args.mappings_dir / f"sub-{bids_id}_ses-{session}_mapping.yaml"
        if not mapping_path.is_file():
            print(f"[SKIP] {tag}: mapping YAML not found: {mapping_path}")
            skipped += 1
            continue

        n_runs, task_key = count_func_runs(mapping_path, session)
        if n_runs is None:
            print(f"[SKIP] {tag}: no func runs found in mapping YAML")
            skipped += 1
            continue

        # --- Events directory ---
        events_dir = args.events_base / f"sub-{nr}" / "events"
        if not events_dir.is_dir():
            print(f"[SKIP] {tag}: events dir not found: {events_dir}")
            skipped += 1
            continue

        source_runs = collect_source_runs(events_dir, nr)
        if not source_runs:
            print(f"[SKIP] {tag}: no parseable event files in {events_dir}")
            skipped += 1
            continue

        # --- Derive mapping: last N source runs ---
        if len(source_runs) < n_runs:
            print(
                f"[WARN] {tag}: only {len(source_runs)} event run(s) but mapping has "
                f"{n_runs} BIDS runs — using all available"
            )
            selected = source_runs
        else:
            selected = source_runs[-n_runs:]

        runs_map = {src: f"{i + 1:02d}" for i, src in enumerate(selected)}

        mapping_str = ", ".join(f"{s}→{b}" for s, b in runs_map.items())
        print(
            f"[OK]  {tag}: {len(source_runs)} event run(s) → "
            f"using last {len(selected)}: {mapping_str}"
        )

        # --- Write per-subject config ---
        out_path = args.out_dir / f"sub-{bids_id}_ses-{session}_events_config.yaml"

        # yaml.dump sorts keys by default; preserve insertion order for runs
        cfg = {
            "subject_nr": nr,
            "bids_id": bids_id,
            "session": session,
            "task": args.task,
            "runs": runs_map,
        }
        with out_path.open("w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        written += 1

    print(f"\nDone: {written} config(s) written to {args.out_dir}, {skipped} skipped.")
    if written:
        print("Review the generated configs, edit if needed, then run copy_events.py --config-dir.")


if __name__ == "__main__":
    main()
