#!/usr/bin/env python3
"""
Extract PatientAge / PatientSex from mrdata TWIX headers (Siemens raw-data
sidecar .yml files) for every subject in a study subject list, write a
demographics CSV, and optionally merge the values into the subject list itself.

Expected layout: <experiments-dir>/<pseudonym>/TWIX/*.yml, with the subject
list carrying at least the columns ``Pseudonym`` and ``Sex``.

Run on the machine where mrdata is mounted, from the directory containing the
subject list (or pass --subject-list/--out explicitly):

    cd /path/to/study/data
    python3 extract_demographics.py --experiments-dir /path/to/experiments
    python3 extract_demographics.py --experiments-dir ... --merge   # fill Sex/Age
                                                                    # (backup kept)

Design notes
------------
* stdlib only -- no pandas on the cluster required.
* Reads EVERY *.yml under <experiments>/<pseudonym>/TWIX/, not just the first,
  and reports subjects whose files disagree on age or sex (the check is what
  makes the single value trustworthy).
* The merge preserves the subject list byte-for-byte outside the touched cells
  (zero-padded BIDS-IDs, dd.mm.yyyy dates, CRLF endings, comments).  Age goes
  into its own column inserted after Sex -- PatientAge is age at measurement,
  NOT a date of birth, so DateOfBirth is never written.  Idempotent: an
  existing Age column is reused, existing non-conflicting values are kept, and
  conflicts are reported instead of overwritten.
"""

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

CWD = Path.cwd()

AGE_RE = re.compile(r"^PatientAge:\s*(\S+)")
SEX_RE = re.compile(r"^PatientSex:\s*(\S+)")


def scan_subject(twix_dir: Path):
    """Collect unique ages/sexes across every yml of one subject."""
    ages, sexes, n = set(), set(), 0
    for yml in sorted(twix_dir.glob("*.yml")):
        n += 1
        try:
            text = yml.read_text(errors="replace")
        except OSError as e:
            print(f"  WARNING: unreadable {yml.name}: {e}", file=sys.stderr)
            continue
        for line in text.splitlines():
            m = AGE_RE.match(line)
            if m:
                ages.add(m.group(1))
            m = SEX_RE.match(line)
            if m:
                sexes.add(m.group(1))
    return ages, sexes, n


def read_rows(path: Path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", required=True,
                    help="mrdata experiments root "
                         "(contains one <pseudonym>/TWIX/ folder per subject)")
    ap.add_argument("--subject-list", default=str(CWD / "subject_list.csv"))
    ap.add_argument("--out", default=str(CWD / "demographics.csv"))
    ap.add_argument("--merge", action="store_true",
                    help="also fill Sex and Age into the subject list "
                         "(a .backup copy is written first)")
    args = ap.parse_args()

    exp = Path(args.experiments_dir)
    if not exp.is_dir():
        sys.exit(f"experiments dir not found: {exp}\n"
                 f"(run this on the machine where mrdata is mounted, or pass "
                 f"--experiments-dir)")

    header, data = read_rows(Path(args.subject_list))
    idx = {c.strip(): i for i, c in enumerate(header)}
    i_pseudo = idx["Pseudonym"]

    demo = {}          # pseudonym -> (age, sex, n_yml)
    problems = []
    for row in data:
        p = row[i_pseudo].strip()
        if not p:
            continue
        twix = exp / p / "TWIX"
        if not twix.is_dir():
            problems.append(f"{p}: no TWIX dir")
            continue
        ages, sexes, n = scan_subject(twix)
        if len(ages) > 1 or len(sexes) > 1:
            problems.append(f"{p}: INCONSISTENT across {n} yml files "
                            f"(ages {sorted(ages)}, sexes {sorted(sexes)})")
            continue
        if not ages or not sexes:
            problems.append(f"{p}: no PatientAge/PatientSex in {n} yml files")
            continue
        demo[p] = (ages.pop(), sexes.pop(), n)

    # ── demographics CSV ──
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Pseudonym", "Age", "Sex", "n_twix_yml"])
        for p, (age, sex, n) in demo.items():
            w.writerow([p, age, sex, n])
    print(f"{args.out}: {len(demo)} subjects")
    for msg in problems:
        print(f"  PROBLEM: {msg}")

    ages = sorted(int(a) for a, _, _ in demo.values())
    sexes = [s for _, s, _ in demo.values()]
    if ages:
        mean = sum(ages) / len(ages)
        sd = ((sum((a - mean) ** 2 for a in ages) / (len(ages) - 1)) ** 0.5
              if len(ages) > 1 else float("nan"))
        print(f"  N={len(ages)}  age {mean:.1f} +/- {sd:.1f} "
              f"(range {ages[0]}-{ages[-1]})  "
              f"sex M={sexes.count('M')} F={sexes.count('F')}")

    # ── optional merge into the subject list ──
    if not args.merge:
        return
    src = Path(args.subject_list)
    backup = src.with_suffix(".backup_pre_demographics.csv")
    if not backup.exists():
        shutil.copy2(src, backup)
        print(f"backup written: {backup.name}")

    i_sex = idx["Sex"]
    if "Age" in idx:
        i_age = idx["Age"]
    else:
        i_age = i_sex + 1
        header.insert(i_age, "Age")
        for row in data:
            row.insert(i_age, "")

    filled, conflicts = 0, []
    for row in data:
        p = row[i_pseudo].strip()
        if p not in demo:
            continue
        age, sex, _ = demo[p]
        for i_col, new in ((i_sex, sex), (i_age, age)):
            old = row[i_col].strip()
            if old and old != new:
                conflicts.append(f"{p}: {header[i_col]} has '{old}', "
                                 f"mrdata says '{new}' -- NOT overwritten")
            elif not old:
                row[i_col] = new
                filled += 1

    with open(src, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print(f"merged into {src.name}: {filled} cells filled")
    for c in conflicts:
        print(f"  CONFLICT: {c}")


if __name__ == "__main__":
    main()
