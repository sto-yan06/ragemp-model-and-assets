"""
RPF Packer — injects handling.meta into an RPF7 archive.

Merges user-edited fields into the original handling.meta from the RPF,
preserving all fields the game expects (damage, flags, SubHandlingData, etc.).

Usage:
    python processor/rpf_packer.py <rpf_path> <handling_meta_path>

A backup of the original RPF is created as .rpf.bak before modification.
"""
import sys
import os
import shutil
import logging
import xml.etree.ElementTree as ET

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gta_converter.rpf_parser import RPFFile, find_entry_by_name, replace_file_in_rpf

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def extract_handling_from_rpf(rpf_path):
    """Extract the original handling.meta content from the RPF."""
    with open(rpf_path, 'rb') as f:
        rpf_data = f.read()
    rpf = RPFFile(rpf_data)
    entry = find_entry_by_name(rpf, 'handling.meta')
    if entry is None:
        return None
    data = rpf.extract_file(entry)
    if data:
        return data.decode('utf-8', errors='replace')
    return None


def merge_handling_xml(original_xml, user_xml):
    """Merge user-edited fields into the original handling.meta XML.
    
    Strategy:
    - Parse both XMLs
    - Find the CHandlingData Item in both
    - For each field in the user XML, update the corresponding field in the original
    - Keep all original fields that aren't in the user XML (damage, flags, SubHandling, etc.)
    - Preserve the original handlingName (model ID) always
    """
    try:
        orig_root = ET.fromstring(original_xml)
        user_root = ET.fromstring(user_xml)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return None
    
    # Find CHandlingData items
    orig_item = orig_root.find('.//Item[@type="CHandlingData"]')
    user_item = user_root.find('.//Item[@type="CHandlingData"]')
    
    if orig_item is None:
        logger.error("No CHandlingData found in original handling.meta")
        return None
    if user_item is None:
        logger.error("No CHandlingData found in user handling.meta")
        return None
    
    # Get original handlingName — must be preserved
    orig_name_elem = orig_item.find('handlingName')
    orig_name = orig_name_elem.text if orig_name_elem is not None else None
    
    # Build set of user-provided fields
    # Skip handlingName (preserve original) and SubHandlingData (complex structure)
    skip_tags = {'handlingName', 'SubHandlingData'}
    
    for user_child in user_item:
        tag = user_child.tag
        if tag in skip_tags:
            continue
        
        # Find corresponding element in original
        orig_child = orig_item.find(tag)
        if orig_child is not None:
            # Update attributes (value="...", x="...", y="...", z="...")
            if user_child.attrib:
                orig_child.attrib.update(user_child.attrib)
            # Update text content
            if user_child.text and user_child.text.strip():
                orig_child.text = user_child.text
        else:
            # Field doesn't exist in original — add it before SubHandlingData
            sub_handling = orig_item.find('SubHandlingData')
            if sub_handling is not None:
                idx = list(orig_item).index(sub_handling)
                orig_item.insert(idx, user_child)
            else:
                orig_item.append(user_child)
    
    # Serialize back to XML string
    # Use the original XML declaration
    result = '<?xml version="1.0" encoding="UTF-8"?>\n'
    result += ET.tostring(orig_root, encoding='unicode')
    # Add trailing newline
    if not result.endswith('\n'):
        result += '\n'
    
    return result


def verify_rpf(rpf_path):
    """Verify the modified RPF is still valid by re-parsing and extracting handling.meta."""
    with open(rpf_path, 'rb') as f:
        rpf_data = f.read()
    
    rpf = RPFFile(rpf_data)
    entry = find_entry_by_name(rpf, 'handling.meta')
    if entry is None:
        return False, "handling.meta not found after modification"
    
    data = rpf.extract_file(entry)
    if data is None:
        return False, "Failed to extract handling.meta after modification"
    
    # Verify it's valid XML
    try:
        text = data.decode('utf-8')
        root = ET.fromstring(text)
        item = root.find('.//Item[@type="CHandlingData"]')
        if item is None:
            return False, "No CHandlingData found in extracted handling.meta"
        name_elem = item.find('handlingName')
        if name_elem is None:
            return False, "No handlingName found in extracted handling.meta"
        return True, f"Verified OK — handlingName={name_elem.text}, size={len(data)} bytes"
    except Exception as e:
        return False, f"Extracted data is not valid XML: {e}"


def main():
    if len(sys.argv) < 3:
        print("Usage: python rpf_packer.py <rpf_path> <handling_meta_path>")
        sys.exit(1)

    rpf_path = sys.argv[1]
    inject_path = sys.argv[2]

    if not os.path.exists(rpf_path):
        print(f"ERROR: RPF file not found: {rpf_path}")
        sys.exit(1)

    if not os.path.exists(inject_path):
        print(f"ERROR: Handling meta not found: {inject_path}")
        sys.exit(1)

    # Read user's handling.meta
    with open(inject_path, 'r', encoding='utf-8') as f:
        user_xml = f.read()

    if not user_xml.strip():
        print("ERROR: Handling meta file is empty")
        sys.exit(1)

    # Step 1: Extract original handling.meta from RPF
    print("Extracting original handling.meta from RPF...")
    original_xml = extract_handling_from_rpf(rpf_path)
    if original_xml is None:
        print("ERROR: No handling.meta found in RPF")
        sys.exit(1)
    print(f"  Original handling.meta: {len(original_xml)} bytes")

    # Step 2: Merge user changes into original
    print("Merging user changes into original...")
    merged_xml = merge_handling_xml(original_xml, user_xml)
    if merged_xml is None:
        print("ERROR: Failed to merge handling XML")
        sys.exit(1)
    print(f"  Merged handling.meta: {len(merged_xml)} bytes")

    merged_data = merged_xml.encode('utf-8')

    # Step 3: Create backup
    backup_path = rpf_path + '.bak'
    if not os.path.exists(backup_path):
        shutil.copy2(rpf_path, backup_path)
        print(f"  Backup: {backup_path}")
    else:
        print(f"  Backup exists: {backup_path}")

    # Step 4: Inject merged handling.meta into RPF
    print("Injecting into RPF...")
    try:
        replace_file_in_rpf(rpf_path, 'handling.meta', merged_data)
    except Exception as e:
        print(f"ERROR: Injection failed: {e}")
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, rpf_path)
            print("Restored from backup.")
        sys.exit(1)

    # Step 5: Verify the modified RPF
    print("Verifying modified RPF...")
    ok, msg = verify_rpf(rpf_path)
    if not ok:
        print(f"ERROR: Verification failed: {msg}")
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, rpf_path)
            print("Restored from backup.")
        sys.exit(1)

    print(f"SUCCESS: {msg}")


if __name__ == '__main__':
    main()
