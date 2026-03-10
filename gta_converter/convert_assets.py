"""
GTA V Format Converter - Orchestrates conversion of processed models/textures
to GTA V native formats using CodeWalker and OpenIV command-line tools.

Target formats:
- Vehicles: .yft + .ytd
- Weapons:  .ydr + .ytd
- Clothes:  .ydd + .ytd
- Maps:     .ymap + .ytyp

Note: This script orchestrates external tools (CodeWalker, OpenIV).
You must have these tools installed and configured in config.json.
"""

import os
import sys
import json
import shutil
import subprocess
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def setup_logging(config):
    log_dir = config.get("logging", {}).get("log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"converter_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("converter")


def check_tools(config, logger):
    """Check if required conversion tools are available."""
    tools_ok = True

    codewalker_path = config["converter"].get("codewalker_path", "")
    openiv_path = config["converter"].get("openiv_path", "")

    if codewalker_path and os.path.exists(codewalker_path):
        logger.info(f"CodeWalker found at: {codewalker_path}")
    else:
        logger.warning(f"CodeWalker not found at: {codewalker_path}")
        logger.info("Download from: https://codewalker.net/")
        tools_ok = False

    if openiv_path and os.path.exists(openiv_path):
        logger.info(f"OpenIV found at: {openiv_path}")
    else:
        logger.warning(f"OpenIV not found at: {openiv_path}")
        logger.info("Download from: https://openiv.com/")
        tools_ok = False

    return tools_ok


def convert_texture_to_ytd(input_png, output_ytd, config, logger):
    """
    Convert a PNG texture to GTA V .ytd format.

    This uses a helper approach:
    1. Create a temporary texture dictionary XML
    2. Use CodeWalker's command-line to build the .ytd
    """
    codewalker = config["converter"].get("codewalker_path", "")

    # Check for CodeWalker RPF Explorer CLI
    cli_path = os.path.join(codewalker, "CodeWalker.exe")
    if not os.path.exists(cli_path):
        logger.warning(f"CodeWalker CLI not found: {cli_path}")
        logger.info(f"Manual conversion needed: {input_png} -> {output_ytd}")
        # Copy the PNG to output as a placeholder
        placeholder_dir = os.path.dirname(output_ytd)
        os.makedirs(placeholder_dir, exist_ok=True)
        shutil.copy2(input_png, output_ytd.replace(".ytd", ".png"))
        return False

    # Create texture dictionary structure for CodeWalker
    tex_name = os.path.splitext(os.path.basename(input_png))[0]
    temp_dir = os.path.join(os.path.dirname(output_ytd), "_temp_ytd")
    os.makedirs(temp_dir, exist_ok=True)

    # Copy texture
    shutil.copy2(input_png, os.path.join(temp_dir, f"{tex_name}.png"))

    try:
        result = subprocess.run(
            [cli_path, "-convert", "-ytd", temp_dir, output_ytd],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info(f"Converted: {output_ytd}")
            return True
        else:
            logger.error(f"Conversion failed: {result.stderr}")
            return False
    except FileNotFoundError:
        logger.error("CodeWalker executable not found")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"Conversion timed out for {input_png}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def organize_for_streaming(input_dir, output_dir, logger):
    """
    Organize already-converted GTA assets into streaming-ready structure.
    Files that are already in GTA format (.yft, .ytd, .ydr, etc.) are
    just sorted and copied to the correct output directories.
    """
    gta_extensions = {
        ".yft": "vehicles",
        ".ydr": "weapons",
        ".ydd": "clothes",
        ".ytd": "textures",
        ".ymap": "maps",
        ".ytyp": "maps",
        ".meta": "meta"
    }

    organized = {cat: 0 for cat in set(gta_extensions.values())}

    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in gta_extensions:
                continue

            category = gta_extensions[ext]

            # Pair .ytd with their model type if possible
            if ext == ".ytd":
                base = os.path.splitext(filename)[0]
                for sibling in files:
                    s_ext = os.path.splitext(sibling)[1].lower()
                    s_base = os.path.splitext(sibling)[0]
                    if s_base == base:
                        if s_ext == ".yft":
                            category = "vehicles"
                        elif s_ext == ".ydr":
                            category = "weapons"
                        elif s_ext == ".ydd":
                            category = "clothes"
                        break

            target_dir = os.path.join(output_dir, category)
            os.makedirs(target_dir, exist_ok=True)

            src = os.path.join(root, filename)
            dst = os.path.join(target_dir, filename)

            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                organized[category] += 1
                logger.debug(f"Organized: {filename} -> {category}/")

    return organized


def generate_conversion_report(output_dir, organized, logger):
    """Generate a report of what was converted/organized."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "categories": {}
    }

    for category, count in organized.items():
        cat_dir = os.path.join(output_dir, category)
        if os.path.exists(cat_dir):
            files = os.listdir(cat_dir)
            report["categories"][category] = {
                "count": len(files),
                "files": files
            }

    report_path = os.path.join(output_dir, "conversion_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Conversion report written to {report_path}")
    return report


def main():
    config = load_config()
    logger = setup_logging(config)
    conv_config = config["converter"]

    logger.info("=" * 60)
    logger.info("GTA V Format Converter - Starting")
    logger.info("=" * 60)

    # Check tools
    tools_available = check_tools(config, logger)
    if not tools_available:
        logger.warning("Some tools are missing. Will organize existing GTA files only.")

    input_dir = conv_config["input_dir"]
    output_dir = conv_config["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    # Also process assets that came from the scraper (already in GTA format)
    assets_dir = config["extraction"]["output_dir"]

    # Step 1: Organize existing GTA-format files
    logger.info("\n--- Organizing existing GTA format files ---")
    organized = {}

    for source in [input_dir, assets_dir]:
        if os.path.exists(source):
            result = organize_for_streaming(source, output_dir, logger)
            for cat, count in result.items():
                organized[cat] = organized.get(cat, 0) + count

    for cat, count in organized.items():
        if count > 0:
            logger.info(f"  {cat}: {count} files")

    # Step 2: Convert AI-generated textures to .ytd (if tools available)
    if tools_available:
        ai_output = config["ai_textures"]["output_dir"]
        if os.path.exists(ai_output):
            logger.info("\n--- Converting AI textures to .ytd ---")
            for root, dirs, files in os.walk(ai_output):
                for f in files:
                    if f.lower().endswith(".png"):
                        input_png = os.path.join(root, f)
                        output_ytd = os.path.join(
                            output_dir, "textures",
                            os.path.splitext(f)[0] + ".ytd"
                        )
                        convert_texture_to_ytd(input_png, output_ytd, config, logger)

    # Generate report
    generate_conversion_report(output_dir, organized, logger)

    logger.info("\nConversion complete.")


if __name__ == "__main__":
    main()
