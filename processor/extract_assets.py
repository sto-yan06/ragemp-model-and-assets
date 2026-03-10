"""
Asset Extraction & Sorting - Extracts downloaded archives and sorts files
by type into the correct asset directories.
"""

import os
import sys
import json
import shutil
import zipfile
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

# GTA V asset file extensions and their categories
ASSET_CATEGORIES = {
    "vehicles": [".yft"],
    "weapons": [".ydr"],
    "clothes": [".ydd"],
    "textures": [".ytd"],
    "maps": [".ymap", ".ytyp"],
    "meta": [".meta", ".xml"],
    "audio": [".awc"],
    "misc": []
}

# Reverse lookup: extension -> category
EXTENSION_MAP = {}
for category, extensions in ASSET_CATEGORIES.items():
    for ext in extensions:
        EXTENSION_MAP[ext] = category


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def setup_logging(config):
    log_dir = config.get("logging", {}).get("log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"extractor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("extractor")


def extract_archive(archive_path, extract_to, logger):
    """Extract a zip/rar archive to target directory."""
    extracted_files = []

    if archive_path.endswith(".zip"):
        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                # Security: check for path traversal
                for member in z.namelist():
                    member_path = os.path.realpath(os.path.join(extract_to, member))
                    extract_real = os.path.realpath(extract_to)
                    if not member_path.startswith(extract_real):
                        logger.warning(f"Skipping unsafe path in archive: {member}")
                        continue

                z.extractall(extract_to)
                extracted_files = z.namelist()
                logger.info(f"Extracted {len(extracted_files)} files from {archive_path}")
        except zipfile.BadZipFile:
            logger.error(f"Bad zip file: {archive_path}")
        except Exception as e:
            logger.error(f"Error extracting {archive_path}: {e}")
    else:
        logger.warning(f"Unsupported archive format: {archive_path}")

    return extracted_files


def sort_assets(extract_dir, output_dir, supported_extensions, logger):
    """Walk extracted files and sort them into categorized directories."""
    sorted_count = {cat: 0 for cat in ASSET_CATEGORIES}
    sorted_files = []

    for root, dirs, files in os.walk(extract_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            ext = os.path.splitext(filename)[1].lower()

            if ext not in supported_extensions:
                continue

            category = EXTENSION_MAP.get(ext, "misc")

            # Special handling: .ytd files are textures, but if found alongside
            # .yft they belong to vehicles, alongside .ydr to weapons, etc.
            if ext == ".ytd":
                sibling_exts = set()
                for sibling in os.listdir(root):
                    sibling_exts.add(os.path.splitext(sibling)[1].lower())

                if ".yft" in sibling_exts:
                    category = "vehicles"
                elif ".ydr" in sibling_exts:
                    category = "weapons"
                elif ".ydd" in sibling_exts:
                    category = "clothes"
                else:
                    category = "textures"

            target_dir = os.path.join(output_dir, category)
            os.makedirs(target_dir, exist_ok=True)

            target_path = os.path.join(target_dir, filename)

            # Handle duplicates by appending a counter
            if os.path.exists(target_path):
                base, extension = os.path.splitext(filename)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(target_dir, f"{base}_{counter}{extension}")
                    counter += 1

            shutil.copy2(filepath, target_path)
            sorted_count[category] += 1
            sorted_files.append(target_path)
            logger.debug(f"Sorted: {filename} -> {category}/")

    return sorted_count, sorted_files


def generate_asset_manifest(output_dir, logger):
    """Generate a manifest of all sorted assets."""
    manifest = {
        "generated": datetime.now().isoformat(),
        "categories": {}
    }

    for category in ASSET_CATEGORIES:
        cat_dir = os.path.join(output_dir, category)
        if os.path.exists(cat_dir):
            files = os.listdir(cat_dir)
            manifest["categories"][category] = {
                "count": len(files),
                "files": files,
                "total_size_mb": round(
                    sum(os.path.getsize(os.path.join(cat_dir, f)) for f in files) / (1024 * 1024), 2
                )
            }

    manifest_path = os.path.join(output_dir, "asset_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Asset manifest written to {manifest_path}")
    return manifest


def main():
    config = load_config()
    logger = setup_logging(config)
    extract_config = config["extraction"]

    input_dir = extract_config["input_dir"]
    output_dir = extract_config["output_dir"]
    supported_ext = extract_config["supported_extensions"]

    logger.info("=" * 60)
    logger.info("Asset Extraction & Sorting - Starting")
    logger.info("=" * 60)

    # Create output directories
    os.makedirs(output_dir, exist_ok=True)
    temp_extract = os.path.join(output_dir, "_temp_extract")
    os.makedirs(temp_extract, exist_ok=True)

    # Find all archives in the download directory (recursively)
    archives = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f.endswith(".zip"):
                archives.append(os.path.join(root, f))

    logger.info(f"Found {len(archives)} archives to process")

    # Extract all archives
    for archive_path in archives:
        archive_name = os.path.splitext(os.path.basename(archive_path))[0]
        extract_to = os.path.join(temp_extract, archive_name)
        os.makedirs(extract_to, exist_ok=True)

        logger.info(f"Extracting: {archive_path}")
        extract_archive(archive_path, extract_to, logger)

    # Sort extracted files
    logger.info("Sorting extracted assets...")
    counts, sorted_files = sort_assets(temp_extract, output_dir, supported_ext, logger)

    # Report
    logger.info("\n--- Extraction Summary ---")
    for category, count in counts.items():
        if count > 0:
            logger.info(f"  {category}: {count} files")
    logger.info(f"  Total sorted: {sum(counts.values())} files")

    # Generate manifest
    manifest = generate_asset_manifest(output_dir, logger)

    # Cleanup temp directory
    shutil.rmtree(temp_extract, ignore_errors=True)
    logger.info("Extraction complete.")

    return sorted_files


if __name__ == "__main__":
    main()
