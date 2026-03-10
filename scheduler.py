"""
Daily Pipeline Scheduler

Runs the full asset pipeline on a daily schedule.
Can be run as a long-running process or set up via Windows Task Scheduler / Linux cron.

Usage:
    python scheduler.py              # Run as daemon
    python scheduler.py --run-now    # Run pipeline immediately, then exit

Windows Task Scheduler setup:
    Action: Start a program
    Program: python
    Arguments: "D:\\ragemp model and assets\\orchestrator.js"
    Trigger: Daily at 03:00 AM

Linux cron example:
    0 3 * * * cd /path/to/pipeline && node orchestrator.js >> logs/cron.log 2>&1
"""

import os
import sys
import json
import subprocess
import time
import logging
from datetime import datetime

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(LOG_DIR, "scheduler.log")),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("scheduler")


def run_pipeline(logger):
    """Run the full pipeline via the Node.js orchestrator."""
    orchestrator_path = os.path.join(os.path.dirname(__file__), "orchestrator.js")

    logger.info("Starting full pipeline run...")
    start = time.time()

    try:
        result = subprocess.run(
            ["node", orchestrator_path],
            cwd=os.path.dirname(__file__),
            capture_output=True,
            text=True,
            timeout=3 * 60 * 60  # 3 hour max
        )

        elapsed = int(time.time() - start)
        if result.returncode == 0:
            logger.info(f"Pipeline completed successfully in {elapsed}s")
        else:
            logger.error(f"Pipeline failed after {elapsed}s")
            logger.error(f"STDERR: {result.stderr[-500:]}")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        logger.error("Pipeline timed out after 3 hours")
        return False
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        return False


def run_scheduler(logger, config):
    """Run as a long-running scheduler daemon."""
    try:
        import schedule
    except ImportError:
        logger.error("'schedule' package not installed. Run: pip install schedule")
        sys.exit(1)

    pipeline_config = config.get("pipeline", {})
    scrape_hour = pipeline_config.get("scrape_hour", 3)

    # Schedule the full pipeline to run daily
    schedule.every().day.at(f"{scrape_hour:02d}:00").do(run_pipeline, logger)

    logger.info(f"Scheduler started. Pipeline scheduled daily at {scrape_hour:02d}:00")
    logger.info("Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")


def main():
    logger = setup_logging()
    config = load_config()

    if "--run-now" in sys.argv:
        logger.info("Running pipeline immediately (--run-now)")
        success = run_pipeline(logger)
        sys.exit(0 if success else 1)
    else:
        run_scheduler(logger, config)


if __name__ == "__main__":
    main()
