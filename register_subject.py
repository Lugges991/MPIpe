#!/usr/bin/env python3
"""register_subject.py - Stage-0 helper: enroll a new subject/session into the
BIDS dataset's identity mapping files.

Creates or updates two files in the BIDS root:
  participants.tsv       - BIDS standard; one row per subject, demographics only
  code/sessions_map.tsv  - per-session ID map: scanner_id, beh_id, BIDS IDs

Usage
-----
# New subject, new session
python register_subject.py \\
    --bids-root /data/BIDS \\
    --scanner-id TYCM-RTYX \\
    --session 01 \\
    --beh-id P0042_S1 \\
    --age 28 --sex F

# Existing subject, second session (provide --subject to skip auto-increment)
python register_subject.py \\
    --bids-root /data/BIDS \\
    --scanner-id ABCD-EFGH \\
    --session 02 \\
    --beh-id P0042_S2 \\
    --subject 01
"""

import argparse
import csv
import sys
from pathlib import Path


PARTICIPANTS_TSV = "participants.tsv"
SESSIONS_MAP_TSV = "code/sessions_map.tsv"

PARTICIPANTS_HEADER = ["participant_id", "age", "sex"]
SESSIONS_HEADER = ["participant_id", "session_id", "scanner_id", "beh_id"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _write_tsv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _next_subject_number(participants_rows: list[dict]) -> int:
    """Return the next available subject number (max existing + 1, or 1)."""
    nums = []
    for row in participants_rows:
        pid = row.get("participant_id", "")
        label = pid.removeprefix("sub-")
        if label.isdigit():
            nums.append(int(label))
    return max(nums, default=0) + 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Enroll a subject/session into participants.tsv and code/sessions_map.tsv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--bids-root", required=True, type=Path,
                   help="BIDS dataset root directory")
    p.add_argument("--scanner-id", required=True,
                   help="Scanner pseudonym (raw folder name, e.g. TYCM-RTYX)")
    p.add_argument("--session", required=True,
                   help="Session label (e.g. 01 or 02)")
    p.add_argument("--beh-id", required=True,
                   help="Behavioral/stimulus system pseudonym for this session")
    p.add_argument("--subject",
                   help="BIDS subject number (e.g. 01). If omitted, auto-increments.")
    p.add_argument("--age", default="n/a", help="Age at first session [n/a]")
    p.add_argument("--sex", default="n/a", help="Biological sex (M/F) [n/a]")
    args = p.parse_args()

    if not args.bids_root.is_dir():
        sys.exit(f"BIDS root not found: {args.bids_root}")

    participants_path = args.bids_root / PARTICIPANTS_TSV
    sessions_map_path = args.bids_root / SESSIONS_MAP_TSV

    participants_rows = _read_tsv(participants_path)
    sessions_rows = _read_tsv(sessions_map_path)

    # Normalise session label
    session_id = "ses-" + args.session.removeprefix("ses-").zfill(2) if args.session.isdigit() \
        else "ses-" + args.session.removeprefix("ses-")

    # Guard: scanner_id must be unique across all sessions
    for row in sessions_rows:
        if row.get("scanner_id", "").strip() == args.scanner_id.strip():
            sys.exit(
                f"Error: scanner_id '{args.scanner_id}' is already registered "
                f"(participant={row['participant_id']}, session={row['session_id']}).\n"
                f"Use a different scanner_id or check sessions_map.tsv."
            )

    # Resolve subject number
    if args.subject:
        sub_num = args.subject.removeprefix("sub-").zfill(2)
    else:
        sub_num = str(_next_subject_number(participants_rows)).zfill(2)

    participant_id = f"sub-{sub_num}"

    # Add to participants.tsv only if this is a new subject
    existing_pids = {r["participant_id"] for r in participants_rows}
    if participant_id not in existing_pids:
        participants_rows.append({
            "participant_id": participant_id,
            "age": args.age,
            "sex": args.sex,
        })
        _write_tsv(participants_path, PARTICIPANTS_HEADER, participants_rows)
        print(f"[participants.tsv] Added {participant_id} (age={args.age}, sex={args.sex})")
    else:
        print(f"[participants.tsv] {participant_id} already exists — skipped.")

    # Append to sessions_map.tsv
    sessions_rows.append({
        "participant_id": participant_id,
        "session_id": session_id,
        "scanner_id": args.scanner_id,
        "beh_id": args.beh_id,
    })
    _write_tsv(sessions_map_path, SESSIONS_HEADER, sessions_rows)
    print(f"[sessions_map.tsv] Added {participant_id} {session_id} "
          f"(scanner_id={args.scanner_id}, beh_id={args.beh_id})")

    print(f"\nRegistered: {participant_id}")
    print(f"  Next steps:")
    print(f"    git -C {args.bids_root} add participants.tsv code/sessions_map.tsv")
    print(f"    git -C {args.bids_root} commit -m 'Enroll {participant_id} {session_id} ({args.scanner_id})'")


if __name__ == "__main__":
    main()
