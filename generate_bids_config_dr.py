#!/usr/bin/env python3
"""generate_multisession_bids_config.py - Single-session, multi-run BIDS config generator

This script generates a YAML mapping for single-session datasets with multiple runs where each run contains:
- EPI and bSSFP functional sequences 
- MPRAGE anatomical images (shared across runs)
- Reversed phase encoding images for topup
- B1 maps

Expected folder structure:
- Each folder represents a series with naming like: XXXXX_sequence_details/
- Runs are identified by run numbers in folder names
- Test runs are automatically skipped
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required - install with `pip install pyyaml`")

# Patterns for your specific data
PATTERNS = {
    "anat": {
        "T1w": re.compile(r"(?i)(MPRAGE|T1|anatomical)", re.I)
    },
    "func": {
        "epi": re.compile(r"(?i)(ep3d|epi|bold)", re.I),
        "bssfp": re.compile(r"(?i)(3DbSSFP|bssfp|ssfp)", re.I)
    },
    "fmap": {
        "epi_rev": re.compile(r"(?i)(revPE|reversed|topup|PA)", re.I),
        "b1map": re.compile(r"(?i)b1map", re.I)
    }
}

SKIP_PATTERNS = re.compile(r"(?i)(localizer|scout|B0_Map|aa_B0Mapping|replaced_|test)", re.I)


def natural_sort_key(text: str):
    """Natural sorting for alphanumeric strings."""
    import itertools
    import re
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', text)]


def deduplicate_folders(folders: List[Path]) -> List[Path]:
    """Deduplicate folders with same suffix by keeping the one with highest prefix number."""
    from collections import defaultdict
    
    # Group folders by their suffix (everything after the first underscore or the whole name)
    suffix_groups = defaultdict(list)
    
    for folder in folders:
        folder_name = folder.name
        # Extract suffix - look for patterns like "XXXXX_suffix" or just use the whole name
        # For run folders, we want to group by the run part (e.g., "run01")
        
        # Try to extract the meaningful suffix after numbers/prefix
        parts = folder_name.split('_')
        if len(parts) > 1:
            # Use everything after the first part as the key for grouping
            suffix = '_'.join(parts[1:])
        else:
            # If no underscore, use the whole name
            suffix = folder_name
            
        suffix_groups[suffix].append(folder)
    
    # For each group, keep only the folder with the highest prefix number
    deduplicated = []
    for suffix, folder_list in suffix_groups.items():
        if len(folder_list) == 1:
            # No duplicates, keep it
            deduplicated.extend(folder_list)
        else:
            # Multiple folders with same suffix, keep the one with highest prefix number
            def extract_prefix_number(folder_path):
                name = folder_path.name
                # Extract leading numbers
                prefix_match = re.match(r'^(\d+)', name)
                return int(prefix_match.group(1)) if prefix_match else 0
            
            # Sort by prefix number and take the last (highest)
            highest_prefix_folder = max(folder_list, key=extract_prefix_number)
            deduplicated.append(highest_prefix_folder)
            
            print(f"Found duplicate folders for '{suffix}': {[f.name for f in folder_list]}")
            print(f"Selected: {highest_prefix_folder.name} (highest prefix number)")
    
    return deduplicated


def scan_source(source: Path) -> List[Path]:
    """Get all directories in source folder, sorted naturally, with duplicates removed."""
    all_folders = [p for p in source.iterdir() if p.is_dir()]
    deduplicated_folders = deduplicate_folders(all_folders)
    return sorted(deduplicated_folders, key=lambda p: natural_sort_key(p.name))


def extract_session_run_info(folder_name: str) -> tuple:
    """Extract session and run information from folder name."""
    # All data is from one session, just extract run numbers
    
    # Look for run indicators  
    run_match = re.search(r'run(\d+)', folder_name, re.I)
    if run_match:
        run_num = int(run_match.group(1))
        return 1, run_num  # session 1, actual run number
    
    # For non-run specific files (anat, fieldmaps), assign to session 1
    return 1, 1


def categorise_multisession(folders: List[Path], task_name: str = "prf", session_id: str = "01") -> Dict:
    """Categorise folders into BIDS structure with single session, multiple runs."""
    session_key = f"ses-{session_id}"
    mapping = {session_key: {}}
    epi_run_counter = 0
    bssfp_run_counter = 0
    
    for folder in folders:
        folder_name = folder.name
        
        if SKIP_PATTERNS.search(folder_name):
            continue
            
        session, _ = extract_session_run_info(folder_name)
        
        # Check for anatomical
        if PATTERNS["anat"]["T1w"].search(folder_name):
            if "anat" not in mapping[session_key]:
                mapping[session_key]["anat"] = {}
            if "T1w" not in mapping[session_key]["anat"]:
                mapping[session_key]["anat"]["T1w"] = []
            mapping[session_key]["anat"]["T1w"].append(folder_name)
            continue
            
        # Check for fieldmaps first (before functional to catch revPE)
        if PATTERNS["fmap"]["epi_rev"].search(folder_name):
            if "fmap" not in mapping[session_key]:
                mapping[session_key]["fmap"] = {}
            if "dir" not in mapping[session_key]["fmap"]:
                mapping[session_key]["fmap"]["dir"] = {}
            mapping[session_key]["fmap"]["dir"]["PA"] = folder_name
            continue
            
        if PATTERNS["fmap"]["b1map"].search(folder_name):
            if "fmap" not in mapping[session_key]:
                mapping[session_key]["fmap"] = {}
            if "dir" not in mapping[session_key]["fmap"]:
                mapping[session_key]["fmap"]["dir"] = {}
            mapping[session_key]["fmap"]["dir"]["b1map"] = folder_name
            continue
        
        # Check for functional sequences (after fieldmaps to avoid revPE confusion)
        if PATTERNS["func"]["epi"].search(folder_name) and not PATTERNS["fmap"]["epi_rev"].search(folder_name):
            epi_run_counter += 1
            run_label = f"run-{epi_run_counter:02d}"
            
            if "func" not in mapping[session_key]:
                mapping[session_key]["func"] = {}
            if task_name not in mapping[session_key]["func"]:
                mapping[session_key]["func"][task_name] = {}
            if run_label not in mapping[session_key]["func"][task_name]:
                mapping[session_key]["func"][task_name][run_label] = {}
                
            mapping[session_key]["func"][task_name][run_label]["epi"] = folder_name
            continue
            
        if PATTERNS["func"]["bssfp"].search(folder_name):
            bssfp_run_counter += 1
            run_label = f"run-{bssfp_run_counter:02d}"
            
            if "func" not in mapping[session_key]:
                mapping[session_key]["func"] = {}
            if task_name not in mapping[session_key]["func"]:
                mapping[session_key]["func"][task_name] = {}
            if run_label not in mapping[session_key]["func"][task_name]:
                mapping[session_key]["func"][task_name][run_label] = {}
                
            mapping[session_key]["func"][task_name][run_label]["bssfp"] = folder_name
            continue
    
    return mapping


def main():
    parser = argparse.ArgumentParser(description="Generate single-session BIDS mapping with multiple runs (ignoring test runs)")
    parser.add_argument("--source", required=True, type=Path, help="Directory containing run folders")
    parser.add_argument("--out", type=Path, default=Path("mapping_dr.yaml"), help="Output YAML file")
    parser.add_argument("--task", default="prf", help="Task name for functional data")
    parser.add_argument("--session", default="01", help="Session ID (e.g., '01', '02')")
    parser.add_argument("--no-prompt", action="store_true", help="Skip confirmation prompt")
    
    args = parser.parse_args()
    
    if not args.source.is_dir():
        sys.exit(f"Source directory not found: {args.source}")
    
    folders = scan_source(args.source)
    mapping = categorise_multisession(folders, args.task, args.session)
    
    yaml_str = yaml.safe_dump(mapping, sort_keys=False, default_flow_style=False)
    
    print(f"\nProposed single-session mapping for ses-{args.session} (test runs excluded):\n")
    print(yaml_str)
    
    if not args.no_prompt:
        ans = input(f"Write mapping to {args.out.resolve()}? [Y/n] ")
        if ans.strip().lower() not in ("", "y", "yes"):
            print("Aborted - no file written.")
            sys.exit(0)
    
    args.out.write_text(yaml_str)
    print(f"\n✔ Single-session mapping saved to {args.out.resolve()}")
    print(f"   Review/edit if necessary, then run copy2bids.py --config {args.out}")


if __name__ == "__main__":
    main()
