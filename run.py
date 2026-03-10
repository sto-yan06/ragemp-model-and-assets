"""
Modular Pipeline Runner

Run specific pipeline steps for specific asset categories.
Skips steps you don't have tools for (Blender, Stable Diffusion, etc.)

Usage:
    python run.py --category clothes --count 10
    python run.py --category vehicles --count 5
    python run.py --category clothes --count 10 --preview
    python run.py --preview                              # just open preview of existing downloads
    python run.py --category clothes --count 10 --extract # also extract after downloading

Available steps (run individually):
    python run.py --step scrape   --category clothes --count 10
    python run.py --step extract
    python run.py --step build
    python run.py --step spawns
    python run.py --step preview
"""

import os
import sys
import json
import argparse
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def run_scraper(category, count):
    """Run the scraper for a specific category and count."""
    print(f"\n{'='*60}")
    print(f"  Scraping {count} free {category} assets...")
    print(f"{'='*60}\n")

    script = os.path.join(ROOT_DIR, "scraper", "scrape_assets.py")
    result = subprocess.run(
        [sys.executable, script, "--category", category, "--count", str(count)],
        cwd=ROOT_DIR
    )
    return result.returncode == 0


def run_extract():
    """Run the asset extractor."""
    print(f"\n{'='*60}")
    print(f"  Extracting downloaded assets...")
    print(f"{'='*60}\n")

    script = os.path.join(ROOT_DIR, "processor", "extract_assets.py")
    result = subprocess.run([sys.executable, script], cwd=ROOT_DIR)
    return result.returncode == 0


def run_build():
    """Build RageMP stream resources."""
    print(f"\n{'='*60}")
    print(f"  Building RageMP resources...")
    print(f"{'='*60}\n")

    script = os.path.join(ROOT_DIR, "resource_builder", "build_resources.js")
    result = subprocess.run(["node", script], cwd=ROOT_DIR)
    return result.returncode == 0


def run_spawns():
    """Generate spawn scripts."""
    print(f"\n{'='*60}")
    print(f"  Generating spawn scripts...")
    print(f"{'='*60}\n")

    script = os.path.join(ROOT_DIR, "server_scripts", "generate_spawns.js")
    result = subprocess.run(["node", script], cwd=ROOT_DIR)
    return result.returncode == 0


def run_preview():
    """Launch the asset preview dashboard."""
    print(f"\n{'='*60}")
    print(f"  Launching preview dashboard...")
    print(f"{'='*60}\n")

    script = os.path.join(ROOT_DIR, "preview", "server.js")
    config = load_config()
    port = config.get("preview", {}).get("port", 3000)
    print(f"  Open http://127.0.0.1:{port} in your browser")
    print(f"  Press Ctrl+C to stop\n")

    result = subprocess.run(["node", script], cwd=ROOT_DIR)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="RageMP Asset Pipeline - Modular Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --category clothes --count 10
  python run.py --category clothes --count 10 --preview
  python run.py --category vehicles --count 5 --extract
  python run.py --preview
  python run.py --step extract
  python run.py --step build
        """
    )
    parser.add_argument("--category", "-c", choices=["vehicles", "weapons", "clothes", "maps", "houses"],
                        help="Asset category to scrape")
    parser.add_argument("--count", "-n", type=int, default=10,
                        help="Number of assets to download (default: 10)")
    parser.add_argument("--extract", "-e", action="store_true",
                        help="Also extract downloaded archives")
    parser.add_argument("--build", "-b", action="store_true",
                        help="Also build RageMP stream resources")
    parser.add_argument("--preview", "-p", action="store_true",
                        help="Launch visual preview dashboard after downloading")
    parser.add_argument("--step", "-s",
                        choices=["scrape", "extract", "build", "spawns", "preview"],
                        help="Run a single specific step")

    args = parser.parse_args()

    # Single step mode
    if args.step:
        if args.step == "scrape":
            if not args.category:
                parser.error("--category is required for scrape step")
            run_scraper(args.category, args.count)
        elif args.step == "extract":
            run_extract()
        elif args.step == "build":
            run_build()
        elif args.step == "spawns":
            run_spawns()
        elif args.step == "preview":
            run_preview()
        return

    # Preview-only mode
    if args.preview and not args.category:
        run_preview()
        return

    # Must have a category for scraping
    if not args.category:
        parser.error("--category is required (or use --step/--preview)")

    # Run pipeline: scrape -> [extract] -> [build] -> [preview]
    success = run_scraper(args.category, args.count)

    if args.extract and success:
        run_extract()

    if args.build:
        run_build()
        run_spawns()

    if args.preview:
        run_preview()


if __name__ == "__main__":
    main()
