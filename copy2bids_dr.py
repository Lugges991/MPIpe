#!/usr/bin/env python3
"""copy2bids_folders.py - BIDS copy script for folder-based source data

This script copies files into BIDS format when the source data is organized 
in folders (one folder per series) rather than individual files.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError:
    yaml = None


def load_mapping(cfg_path: Path) -> Dict[str, Any]:
    """Load YAML or JSON mapping file."""
    text = cfg_path.read_text()
    if cfg_path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            sys.exit("PyYAML required for YAML configs - install with `pip install pyyaml`")
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"Config file not valid JSON or YAML: {e}")


def copy_file(src: Path, dst: Path, method: str, dry: bool = False):
    """Copy/link a file using the specified method."""
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
    else:
        raise ValueError(f"Unknown method: {method}")


def find_nifti_files(folder: Path) -> list:
    """Find .nii and .nii.gz files in a folder."""
    nifti_files = []
    for pattern in ["*.nii", "*.nii.gz"]:
        nifti_files.extend(folder.glob(pattern))
    return nifti_files


def find_json_files(folder: Path) -> list:
    """Find .json files in a folder."""
    return list(folder.glob("*.json"))


def copy_json_with_metadata(src_json: Path, dst_json: Path, seq_type: str, method: str, dry: bool = False, task_name: str = "task"):
    """Copy JSON file and add sequence type metadata for BIDS compliance."""
    if dry:
        print(f" [DRY] {method.upper():6} {src_json} -> {dst_json} (adding SequenceType: {seq_type}, TaskName: {task_name})")
        return
    
    # Read original JSON
    try:
        with open(src_json, 'r') as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        metadata = {}
    
    # Add required BIDS fields for functional data
    metadata['TaskName'] = task_name  # Required field for functional data
    
    # Add sequence type information for BIDS compliance
    # This preserves the sequence information that was previously in the filename
    metadata['SequenceType'] = seq_type.upper()  # e.g., 'BSSFP', 'EPI'
    if seq_type.lower() == 'bssfp':
        metadata['PulseSequenceDetails'] = 'bSSFP'
    elif seq_type.lower() == 'epi':
        metadata['PulseSequenceDetails'] = 'EP3D'
    
    # Add required PhaseEncodingDirection if not present
    if 'PhaseEncodingDirection' not in metadata:
        # Default to anterior-posterior (j) for functional data
        # This should be updated based on actual acquisition parameters
        metadata['PhaseEncodingDirection'] = 'j'
    
    # Write enhanced JSON to destination
    dst_json.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_json, 'w') as f:
        json.dump(metadata, f, indent=2)


def copy_fmap_json_with_metadata(src_json: Path, dst_json: Path, fmap_type: str, method: str, dry: bool = False):
    """Copy fieldmap JSON file and add BIDS-compliant metadata."""
    if dry:
        print(f" [DRY] {method.upper():6} {src_json} -> {dst_json} (adding fieldmap metadata: {fmap_type})")
        return
    
    # Read original JSON
    try:
        with open(src_json, 'r') as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        metadata = {}
    
    # Add fieldmap-specific metadata for BIDS compliance
    if fmap_type == "PA":
        # Reversed phase encoding for topup correction
        metadata['IntendedFor'] = []  # This should be populated with functional files that use this fieldmap
        # Set PhaseEncodingDirection for PA (posterior-anterior)
        if 'PhaseEncodingDirection' not in metadata:
            metadata['PhaseEncodingDirection'] = 'j-'  # Posterior-Anterior
    elif fmap_type == "b1map":
        # B1 mapping metadata
        metadata['Units'] = 'arbitrary'  # Common for B1 maps
        if 'FlipAngle' not in metadata:
            metadata['FlipAngle'] = []  # Should contain actual flip angles used
        # B1 maps don't typically need PhaseEncodingDirection
    else:
        # For other fieldmap types, add a default PhaseEncodingDirection if not present
        if 'PhaseEncodingDirection' not in metadata:
            metadata['PhaseEncodingDirection'] = 'j'
    
    # Write enhanced JSON to destination
    dst_json.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_json, 'w') as f:
        json.dump(metadata, f, indent=2)


def build_dest_name(subject: str, session: str, suffix: str, ext: str = ".nii.gz") -> str:
    """Build BIDS-compliant filename."""
    return f"sub-{subject}_ses-{session}_{suffix}{ext}"


def main():
    parser = argparse.ArgumentParser(description="Copy folder-based data into BIDS format")
    parser.add_argument("--source", required=True, type=Path, help="Directory containing series folders")
    parser.add_argument("--dest", required=True, type=Path, help="BIDS dataset root directory")
    parser.add_argument("--config", required=True, type=Path, help="YAML mapping file")
    parser.add_argument("--subject", required=True, help="Subject ID (e.g., '01', 'sub01', etc.)")
    parser.add_argument("--session", required=True, help="Session ID (e.g., '01', 'ses01', etc.)")
    parser.add_argument("--method", choices=["copy", "link", "symlink"], default="copy", help="Copy method")
    parser.add_argument("--dry", action="store_true", help="Dry run - show what would be done")
    
    args = parser.parse_args()
    
    if not args.source.is_dir():
        sys.exit(f"Source directory not found: {args.source}")
    if not args.config.is_file():
        sys.exit(f"Config file not found: {args.config}")
    
    # Clean subject and session IDs (remove 'sub-' and 'ses-' prefixes if present)
    subject = args.subject.replace('sub-', '').replace('sub', '')
    session = args.session.replace('ses-', '').replace('ses', '')
    
    mapping = load_mapping(args.config)
    
    # Process the mapping data using the provided session number
    # Take the first (and likely only) session from the mapping
    session_data = next(iter(mapping.values()))
    
    # Use the provided session number for the output structure
    if session.isdigit():
        target_session_key = f"ses-{session.zfill(2)}"
    else:
        target_session_key = f"ses-{session}"
        
    # Process anatomical data
    for anat_type, folder_list in session_data.get("anat", {}).items():
        for folder_name in folder_list:
            folder_path = args.source / folder_name
            if not folder_path.exists():
                print(f"WARNING: Folder not found: {folder_path}")
                continue
            
            # Copy NIfTI files
            nifti_files = find_nifti_files(folder_path)
            if not nifti_files:
                print(f"WARNING: No NIfTI files found in {folder_path}")
                continue
                
            for nifti_file in nifti_files:
                ext = ".nii.gz" if nifti_file.suffix == ".gz" else ".nii"
                dst = args.dest / f"sub-{subject}" / target_session_key / "anat" / build_dest_name(subject, session, anat_type, ext)
                copy_file(nifti_file, dst, args.method, args.dry)
            
            # Copy JSON files
            for json_file in find_json_files(folder_path):
                dst = args.dest / f"sub-{subject}" / target_session_key / "anat" / build_dest_name(subject, session, anat_type, ".json")
                copy_file(json_file, dst, args.method, args.dry)
    
    # Process functional data
    for task, runs in session_data.get("func", {}).items():
        for run_label, sequences in runs.items():
            for seq_type, folder_name in sequences.items():
                if folder_name is None:
                    continue
                    
                folder_path = args.source / folder_name
                if not folder_path.exists():
                    print(f"WARNING: Folder not found: {folder_path}")
                    continue
                
                # Copy NIfTI files
                nifti_files = find_nifti_files(folder_path)
                if not nifti_files:
                    print(f"WARNING: No NIfTI files found in {folder_path}")
                    continue
                    
                for nifti_file in nifti_files:
                    ext = ".nii.gz" if nifti_file.suffix == ".gz" else ".nii"
                    # BIDS compliant: use acquisition label to differentiate sequence types
                    if seq_type.lower() == 'bssfp':
                        bids_suffix = f"task-{task}_acq-bssfp_{run_label}_bold"
                    elif seq_type.lower() == 'epi':
                        bids_suffix = f"task-{task}_acq-epi_{run_label}_bold"
                    else:
                        # Fallback for other sequence types
                        bids_suffix = f"task-{task}_acq-{seq_type}_{run_label}_bold"
                    dst = args.dest / f"sub-{subject}" / target_session_key / "func" / build_dest_name(subject, session, bids_suffix, ext)
                    copy_file(nifti_file, dst, args.method, args.dry)
                
                # Copy JSON files with enhanced metadata
                for json_file in find_json_files(folder_path):
                    # BIDS compliant: use acquisition label to differentiate sequence types
                    if seq_type.lower() == 'bssfp':
                        bids_suffix = f"task-{task}_acq-bssfp_{run_label}_bold"
                    elif seq_type.lower() == 'epi':
                        bids_suffix = f"task-{task}_acq-epi_{run_label}_bold"
                    else:
                        # Fallback for other sequence types
                        bids_suffix = f"task-{task}_acq-{seq_type}_{run_label}_bold"
                    dst = args.dest / f"sub-{subject}" / target_session_key / "func" / build_dest_name(subject, session, bids_suffix, ".json")
                    # Use special JSON copy function to add sequence type metadata
                    copy_json_with_metadata(json_file, dst, seq_type, args.method, args.dry, task_name=task)
    
    # Process fieldmap data
    for fmap_type, fmap_data in session_data.get("fmap", {}).items():
        for key, folder_name in fmap_data.items():
            folder_path = args.source / folder_name
            if not folder_path.exists():
                print(f"WARNING: Folder not found: {folder_path}")
                continue
            
            # Copy NIfTI files
            nifti_files = find_nifti_files(folder_path)
            if not nifti_files:
                print(f"WARNING: No NIfTI files found in {folder_path}")
                continue
                
            for nifti_file in nifti_files:
                ext = ".nii.gz" if nifti_file.suffix == ".gz" else ".nii"
                # BIDS compliant fieldmap naming
                if key == "PA":
                    bids_suffix = "dir-PA_epi"  # Reversed phase encoding for topup
                elif key == "b1map":
                    bids_suffix = "TB1map"  # Transmit B1 map
                else:
                    # Fallback for other fieldmap types
                    bids_suffix = f"fmap-{key}"
                dst = args.dest / f"sub-{subject}" / target_session_key / "fmap" / build_dest_name(subject, session, bids_suffix, ext)
                copy_file(nifti_file, dst, args.method, args.dry)
            
            # Copy JSON files with fieldmap-specific metadata
            for json_file in find_json_files(folder_path):
                # BIDS compliant fieldmap naming
                if key == "PA":
                    bids_suffix = "dir-PA_epi"  # Reversed phase encoding for topup
                elif key == "b1map":
                    bids_suffix = "TB1map"  # Transmit B1 map
                else:
                    # Fallback for other fieldmap types
                    bids_suffix = f"fmap-{key}"
                dst = args.dest / f"sub-{subject}" / target_session_key / "fmap" / build_dest_name(subject, session, bids_suffix, ".json")
                # Use specialized fieldmap JSON copy function
                copy_fmap_json_with_metadata(json_file, dst, key, args.method, args.dry)
    
    print("\n✔ Done (dry-run)" if args.dry else "\n✔ Finished copying files to BIDS format")


if __name__ == "__main__":
    main()
