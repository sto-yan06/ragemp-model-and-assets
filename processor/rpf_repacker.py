"""
DLC.RPF Repacker for Modified Vehicle Assets.

Takes tracked changes (handling.meta edits, texture logo removals) and packs them
back into a new dlc.rpf, preserving the original structure to prevent game crashes.

Workflow:
1. Copy original dlc.rpf to exports/ as the working copy
2. Apply handling.meta changes via replace_file_in_rpf
3. Apply texture changes: PNG → DDS → replace in YTD → replace YTD in RPF
4. Validate the result against the original structure
5. Record the repack in the change tracker
"""

import os
import sys
import json
import struct
import zlib
import shutil
import hashlib
import logging
from pathlib import Path
from datetime import datetime

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from gta_converter.rpf_parser import (
    RPFFile, RPFFileEntry, RPFDirectory,
    replace_file_in_rpf, find_entry_by_name, BLOCK_SIZE, RPF7_MAGIC
)
from processor.change_tracker import ChangeTracker

logger = logging.getLogger(__name__)


def _patch_handling_xml(rpf_path, handling_values):
    """Read original handling.meta from RPF, patch with user values, return new XML bytes.
    
    This preserves the original XML structure and only modifies the values
    the user changed, which is critical for game compatibility.
    """
    import re as _re

    with open(rpf_path, 'rb') as f:
        rpf_data = f.read()

    rpf = RPFFile(rpf_data)
    entry = find_entry_by_name(rpf, "handling.meta")
    if entry is None:
        raise FileNotFoundError("handling.meta not found in RPF")

    original_xml = rpf.extract_file(entry)
    if original_xml is None:
        raise RuntimeError("Could not extract handling.meta from RPF")

    xml_text = original_xml.decode('utf-8', errors='replace')

    # Map of handling.json keys to XML element names
    # Most keys match directly, some need special handling
    DRIVE_TRAIN_MAP = {0: "1.000000", 1: "0.000000", 2: "0.500000"}  # FWD, RWD, AWD

    patched = 0
    for key, value in handling_values.items():
        if key == "strDriveTrain":
            # Special: maps to fDriveBiasFront
            bias = DRIVE_TRAIN_MAP.get(int(value), "0.000000")
            pattern = r'(<fDriveBiasFront\s+value=")[^"]*(")'
            new_xml, n = _re.subn(pattern, rf'\g<1>{bias}\2', xml_text)
            if n > 0:
                xml_text = new_xml
                patched += 1
        elif key.startswith("vecCentreOfMassOffset"):
            # Special: x/y/z components packed into one element
            axis = key[-1].lower()  # X, Y, or Z
            pattern = rf'(<vecCentreOfMassOffset\s[^>]*{axis}=")[^"]*(")'
            fmt_val = f"{float(value):.6f}"
            new_xml, n = _re.subn(pattern, rf'\g<1>{fmt_val}\2', xml_text)
            if n > 0:
                xml_text = new_xml
                patched += 1
        else:
            # Standard: <keyName value="..." />
            # Integer fields (nInitialDriveGears, etc.) stay as int
            INT_FIELDS = {"nInitialDriveGears"}
            if key in INT_FIELDS:
                fmt_val = str(int(value))
            elif isinstance(value, (int, float)):
                fmt_val = f"{float(value):.6f}"
            else:
                fmt_val = str(value)

            pattern = rf'(<{_re.escape(key)}\s+value=")[^"]*(")'
            new_xml, n = _re.subn(pattern, rf'\g<1>{fmt_val}\2', xml_text)
            if n > 0:
                xml_text = new_xml
                patched += 1

    logger.info(f"Patched {patched}/{len(handling_values)} handling values in XML")
    return xml_text.encode('utf-8')


def validate_rpf(original_path, repacked_path):
    """Compare repacked RPF structure against original to catch problems.
    
    Checks:
    - Same number of entries in TOC
    - Same file names in same order
    - Same directory structure
    - No truncated data (file size >= original for append strategy)
    
    Returns:
        dict with validation results
    """
    result = {
        "status": "ok",
        "file_count_match": False,
        "structure_match": False,
        "warnings": [],
        "errors": [],
    }

    try:
        with open(original_path, 'rb') as f:
            orig_data = f.read()
        with open(repacked_path, 'rb') as f:
            new_data = f.read()

        orig_rpf = RPFFile(orig_data)
        new_rpf = RPFFile(new_data)

        orig_files = orig_rpf.list_files()
        new_files = new_rpf.list_files()

        # Check entry count
        if len(orig_rpf.entries) == len(new_rpf.entries):
            result["file_count_match"] = True
        else:
            result["errors"].append(
                f"Entry count mismatch: original={len(orig_rpf.entries)}, repacked={len(new_rpf.entries)}"
            )
            result["status"] = "error"

        # Check file names match
        orig_names = [e.name for e in orig_rpf.entries]
        new_names = [e.name for e in new_rpf.entries]
        if orig_names == new_names:
            result["structure_match"] = True
        else:
            missing = set(orig_names) - set(new_names)
            extra = set(new_names) - set(orig_names)
            if missing:
                result["errors"].append(f"Missing files: {missing}")
            if extra:
                result["warnings"].append(f"Extra files: {extra}")
            result["status"] = "warning" if not missing else "error"

        # Check that modified files can be extracted
        for new_entry in new_files:
            try:
                data = new_rpf.extract_file(new_entry)
                if data is None and new_entry.on_disk_size > 0:
                    result["warnings"].append(f"Cannot extract modified: {new_entry.name}")
            except Exception as e:
                result["warnings"].append(f"Extract error for {new_entry.name}: {e}")

        # File size check
        if len(new_data) < len(orig_data):
            result["warnings"].append(
                f"Repacked file is smaller ({len(new_data):,} < {len(orig_data):,} bytes)"
            )

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))

    if result["errors"]:
        result["status"] = "error"
    elif result["warnings"]:
        result["status"] = "warning"

    return result


def repack_vehicle(preview_dir, output_dir=None):
    """Repack a modified vehicle back into dlc.rpf.
    
    Args:
        preview_dir: Path to the asset's preview directory
        output_dir: Where to write the repacked dlc.rpf (default: preview_dir/exports/)
    
    Returns:
        dict with repack results
    """
    preview_dir = Path(preview_dir)
    tracker = ChangeTracker(str(preview_dir))
    changes = tracker.get_changes()

    if not changes:
        return {"status": "error", "message": "No changes to repack"}

    # Find original RPF
    manifest_path = preview_dir / "manifest.json"
    original_rpf = None

    if manifest_path.exists():
        manifest = json.load(open(manifest_path))
        rpf_src = manifest.get("rpf_source")
        if rpf_src and os.path.exists(rpf_src):
            original_rpf = rpf_src

    # Also check tracker
    if not original_rpf:
        original_rpf = tracker.find_original_rpf(None)

    # Last resort: look for dlc.rpf in the original download's extracted files
    if not original_rpf:
        # Try to find it by scanning the extraction temp area
        safe_name = preview_dir.name
        downloads_dir = preview_dir.parent.parent  # downloads/
        possible = list(Path(downloads_dir).rglob("dlc.rpf"))
        for p in possible:
            if safe_name.lower() in str(p).lower():
                original_rpf = str(p)
                break

    if not original_rpf or not os.path.exists(original_rpf):
        return {
            "status": "error",
            "message": "Original dlc.rpf not found. Re-extract the asset first.",
            "searched": str(original_rpf) if original_rpf else "none"
        }

    # Set up output — always export to new_dlc_exported/<vehicle_name>/
    safe_name = preview_dir.name
    export_base = ROOT_DIR / "new_dlc_exported" / safe_name
    export_base.mkdir(parents=True, exist_ok=True)

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = export_base

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_rpf = output_dir / f"dlc_{timestamp}.rpf"
    # Also always place a "dlc.rpf" (latest) copy in the export folder for easy access
    latest_rpf = export_base / "dlc.rpf"

    # Copy original as working copy
    logger.info(f"Copying original RPF: {original_rpf} → {output_rpf}")
    shutil.copy2(original_rpf, output_rpf)

    applied = 0
    errors = []

    # Apply handling.meta changes
    handling_changes = [c for c in changes if c["type"] == "handling"]
    for change in handling_changes:
        mod_file = preview_dir / change["modified_file"]
        if not mod_file.exists():
            errors.append(f"Modified handling file not found: {mod_file}")
            continue

        target_name = "handling.meta"

        try:
            # If modified_file is handling.json, we need to patch the original XML
            if str(mod_file).endswith(".json"):
                handling_values = json.load(open(mod_file))
                new_data = _patch_handling_xml(str(output_rpf), handling_values)
            else:
                # Direct XML replacement
                with open(mod_file, 'rb') as f:
                    new_data = f.read()

            replace_file_in_rpf(str(output_rpf), target_name, new_data)
            applied += 1
            logger.info(f"Applied handling change: {target_name} ({len(new_data)} bytes)")
        except Exception as e:
            errors.append(f"Failed to apply handling change: {e}")
            logger.error(f"Handling repack error: {e}")

    # Apply texture changes
    texture_changes = [c for c in changes if c["type"] == "texture"]
    if texture_changes:
        logger.info(f"Texture changes detected ({len(texture_changes)})")
        # Texture replacement is complex: PNG → DDS → YTD → RPF
        # For now, log as pending feature and skip gracefully
        for tc in texture_changes:
            logger.warning(f"Texture change for '{tc['texture_name']}' — "
                         f"texture repacking into YTD/RPF is planned for next iteration")
            errors.append(f"Texture repack not yet supported: {tc['texture_name']} "
                        f"(logo-removed PNG saved at {tc['modified_file']})")

    # Validate
    validation = validate_rpf(original_rpf, str(output_rpf))
    logger.info(f"Validation: {validation['status']}")
    if validation["warnings"]:
        for w in validation["warnings"]:
            logger.warning(f"  {w}")
    if validation["errors"]:
        for e in validation["errors"]:
            logger.error(f"  {e}")

    # Copy latest to easy-access location
    try:
        shutil.copy2(output_rpf, latest_rpf)
        logger.info(f"Latest RPF copied to: {latest_rpf}")
    except Exception as e:
        logger.warning(f"Could not copy latest RPF: {e}")

    # Record repack
    tracker.record_repack(str(output_rpf), applied, validation)

    return {
        "status": "ok" if not errors else "partial",
        "output_path": str(output_rpf),
        "export_path": str(latest_rpf),
        "export_dir": str(export_base),
        "changes_applied": applied,
        "changes_total": len(changes),
        "errors": errors,
        "validation": validation,
        "original_rpf": original_rpf,
        "output_size": os.path.getsize(output_rpf),
    }


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Repack modified vehicle into dlc.rpf")
    parser.add_argument("preview_dir", help="Path to asset preview directory")
    parser.add_argument("--output", help="Output directory for repacked RPF")
    args = parser.parse_args()

    result = repack_vehicle(args.preview_dir, args.output)
    print(json.dumps(result, indent=2))
