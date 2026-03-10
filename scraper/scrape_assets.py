"""
RageMP Asset Scraper - Downloads FREE assets only from GTA mod sites.
Respects robots.txt, rate limits, and skips premium/paid content.

Modular usage:
    python scrape_assets.py --category clothes --count 10
    python scrape_assets.py --category vehicles --count 5
    python scrape_assets.py                                # scrape all sources
"""

import os
import sys
import json
import time
import logging
import hashlib
import re
import argparse
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "download_history.json")
METADATA_DIR = os.path.join(ROOT_DIR, "downloads", "_metadata")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def setup_logging(config):
    log_dir = os.path.join(ROOT_DIR, config.get("logging", {}).get("log_dir", "logs"))
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("scraper")


def load_download_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r") as f:
            return json.load(f)
    return {"downloaded": [], "skipped": [], "last_run": None}


def save_download_history(history):
    history["last_run"] = datetime.now().isoformat()
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def load_asset_index():
    """Load the global asset index that tracks all downloaded assets with metadata."""
    index_path = os.path.join(METADATA_DIR, "asset_index.json")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return json.load(f)
    return {"assets": [], "last_updated": None}


def save_asset_index(index):
    """Save the global asset index."""
    os.makedirs(METADATA_DIR, exist_ok=True)
    index["last_updated"] = datetime.now().isoformat()
    index_path = os.path.join(METADATA_DIR, "asset_index.json")
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def is_premium_content(soup_element):
    """Check if a mod page indicates premium/paid content."""
    text = soup_element.get_text().lower()
    # Only match phrases that clearly indicate paid content
    premium_indicators = [
        "premium only", "paid", "patreon", "donate to download",
        "buy now", "purchase", "supporter only",
        "pay to download",
    ]
    for indicator in premium_indicators:
        if indicator in text:
            return True

    classes = " ".join(soup_element.get("class", []))
    if any(kw in classes.lower() for kw in ["premium", "paid", "locked"]):
        return True

    return False


def get_session(config):
    session = requests.Session()
    session.headers.update({
        "User-Agent": config["scraper"]["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    # Set GDPR consent cookies so the site doesn't block download with a consent page
    session.cookies.set("euconsent-v2", "accepted", domain=".gta5-mods.com")
    session.cookies.set("cmp_opt_in", "1", domain=".gta5-mods.com")
    session.cookies.set("__cf_bm", "ok", domain=".gta5-mods.com")

    return session


def extract_thumbnail(session, asset_soup, page_url, download_dir, asset_name, logger):
    """Extract and download the thumbnail/preview image from an asset page."""
    thumb_url = None

    # Strategy 1: og:image meta tag (most reliable on gta5-mods.com)
    og_img = asset_soup.select_one("meta[property='og:image']")
    if og_img:
        thumb_url = og_img.get("content", "")

    # Strategy 2: look for the main mod screenshot on img.gta5-mods.com CDN
    if not thumb_url:
        for img in asset_soup.select("img.img-responsive"):
            src = img.get("src", "") or img.get("data-src", "")
            if src and "img.gta5-mods.com" in src and "/images/" in src:
                thumb_url = src
                break

    # Strategy 3: any <a> linking to a full-res screenshot
    if not thumb_url:
        for a in asset_soup.select("a[href*='img.gta5-mods.com']"):
            href = a.get("href", "")
            if "/images/" in href:
                thumb_url = href
                break

    # Strategy 4: generic fallback for other mod sites
    if not thumb_url:
        for img in asset_soup.select("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if not src:
                continue
            # Skip known non-content images
            if any(skip in src.lower() for skip in [
                "avatar", "icon", "logo", "badge", "flag", "emoji",
                "button", "arrow", "social", "ad", "banner", "pixel",
                "tracking", "1x1", "spacer", "discord", ".svg",
                "quantserve", "default.jpg", "/avatars/"
            ]):
                continue
            thumb_url = src
            break

    if not thumb_url:
        return None

    thumb_url = urljoin(page_url, thumb_url)

    # Download the thumbnail
    thumbs_dir = os.path.join(download_dir, "_thumbnails")
    os.makedirs(thumbs_dir, exist_ok=True)

    ext = os.path.splitext(urlparse(thumb_url).path)[1][:5] or ".jpg"
    # Skip SVG files — they're usually icons/logos, not real previews
    if ext.lower() == ".svg":
        return None
    thumb_filename = f"{asset_name}{ext}"
    thumb_path = os.path.join(thumbs_dir, thumb_filename)

    try:
        resp = session.get(thumb_url, timeout=15)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "svg" in content_type:
            return None
        if "image" in content_type or ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            with open(thumb_path, "wb") as f:
                f.write(resp.content)
            return thumb_path
    except Exception as e:
        logger.debug(f"Failed to download thumbnail: {e}")

    return None


def extract_asset_info(asset_soup, page_url):
    """Extract detailed info from an asset detail page."""
    info = {
        "description": "",
        "author": "",
        "downloads_count": "",
        "rating": "",
        "tags": [],
        "version": "",
        "screenshots": [],
    }

    # Screenshots: collect all mod screenshot URLs from img.gta5-mods.com CDN
    # Extract the mod slug from the page URL to only get relevant images
    page_path = urlparse(page_url).path.strip("/")
    mod_slug = page_path.split("/")[-1] if "/" in page_path else ""

    seen_screenshots = set()
    # Prefer high-quality linked images first
    for a in asset_soup.select("a[href*='img.gta5-mods.com']"):
        href = a.get("href", "")
        if "/images/" in href and href not in seen_screenshots:
            # Only include images that match this mod's slug
            if mod_slug and mod_slug in href:
                seen_screenshots.add(href)
                info["screenshots"].append(href)
    # Also grab img tags for screenshots
    for img in asset_soup.select("img.img-responsive"):
        src = img.get("src", "") or img.get("data-src", "")
        if src and "img.gta5-mods.com" in src and "/images/" in src:
            if mod_slug and mod_slug not in src:
                continue
            # Get a higher quality version by adjusting URL params
            hq_src = re.sub(r'q\d+-w\d+-h\d+-\w+/', 'q95/', src)
            if hq_src not in seen_screenshots:
                seen_screenshots.add(hq_src)
                info["screenshots"].append(hq_src)
    info["screenshots"] = info["screenshots"][:8]  # max 8 screenshots

    # Description
    desc_el = asset_soup.select_one(".mod-description, .description, .mod-desc, #description")
    if desc_el:
        info["description"] = desc_el.get_text(strip=True)[:300]

    # Author
    author_el = asset_soup.select_one(".mod-author a, .author a, [href*='profile'], .username")
    if author_el:
        info["author"] = author_el.get_text(strip=True)

    # Download count
    for el in asset_soup.select(".mod-stats span, .stats span, .download-count"):
        text = el.get_text(strip=True).lower()
        if "download" in text or text.replace(",", "").replace(".", "").isdigit():
            info["downloads_count"] = el.get_text(strip=True)
            break

    # Tags
    for tag in asset_soup.select(".tag, .mod-tag, a[href*='tag']"):
        t = tag.get_text(strip=True)
        if t and len(t) < 30:
            info["tags"].append(t)
    info["tags"] = info["tags"][:10]

    return info


def _extract_mod_links_from_page(soup, base_url, category_segment):
    """Extract individual mod links (/<category>/<slug>) from a listing page."""
    parsed_source = urlparse(base_url)
    skip_segments = {
        "tags", "date", "users", "most-liked", "most-downloaded",
        "highest-rated", "featured", "leaderboard", "categories",
        "comments", "likes", "upload", "login", "register",
        "contact", "privacy", "terms", "dark_mode", "adult_filter",
        "all",
    }
    valid_categories = {"vehicles", "player", "weapons", "maps", "misc", "tools", "paintjobs", "scripts"}
    links = []
    seen = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").split("?")[0].split("#")[0].rstrip("/")
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.hostname and parsed.hostname != parsed_source.hostname:
            continue
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(path_parts) != 2:
            continue
        cat_part, slug_part = path_parts
        if cat_part not in valid_categories or cat_part != category_segment:
            continue
        if slug_part in skip_segments or slug_part.isdigit():
            continue
        normalized = parsed.path.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(abs_url)
    return links


def scrape_gta5mods(session, source_config, config, logger, history, asset_index):
    """Scrape free assets from gta5-mods.com with metadata + thumbnails.
    Supports pagination for tag-filtered pages (e.g. /vehicles/tags/lore-friendly)."""
    url = source_config["url"]
    asset_type = source_config["type"]
    max_items = source_config["max_per_run"]
    delay = config["scraper"]["delay_between_requests_seconds"]
    download_dir = os.path.join(ROOT_DIR, config["scraper"]["download_dir"], asset_type)
    os.makedirs(download_dir, exist_ok=True)

    # Determine pagination settings
    paginate = source_config.get("paginate", False)
    max_pages = source_config.get("max_pages", 1)

    # Determine the URL category path segment
    parsed_source = urlparse(url)
    source_path_parts = [p for p in parsed_source.path.strip("/").split("/") if p]
    category_segment = source_path_parts[0] if source_path_parts else asset_type

    logger.info(f"Scraping {url} for free {asset_type} (max: {max_items}, pages: {max_pages if paginate else 1})...")

    # Phase 1: Collect all mod links from all pages
    all_mod_urls = []
    seen_urls = set()
    pages_to_scrape = max_pages if paginate else 1

    for page_num in range(1, pages_to_scrape + 1):
        if len(all_mod_urls) >= max_items:
            break

        page_url = url if page_num == 1 else f"{url}?page={page_num}"
        logger.info(f"  Fetching page {page_num}/{pages_to_scrape}... ({len(all_mod_urls)} links so far)")

        try:
            time.sleep(delay)
            resp = session.get(page_url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"  Failed to fetch page {page_num}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        page_links = _extract_mod_links_from_page(soup, page_url, category_segment)

        if not page_links:
            logger.info(f"  No mod links on page {page_num}, stopping pagination.")
            break

        new_count = 0
        for link_url in page_links:
            if link_url not in seen_urls:
                seen_urls.add(link_url)
                all_mod_urls.append(link_url)
                new_count += 1
        logger.info(f"  Page {page_num}: {new_count} new links ({len(page_links)} total on page)")

    logger.info(f"Collected {len(all_mod_urls)} unique mod links across {min(page_num, pages_to_scrape)} pages")

    # Phase 2: Visit each mod page and download
    downloaded_files = []
    count = 0

    for mod_idx, full_url in enumerate(all_mod_urls):
        if count >= max_items:
            break

        # Skip if already downloaded
        url_hash = hashlib.md5(full_url.encode()).hexdigest()
        if url_hash in history["downloaded"]:
            logger.debug(f"Already downloaded: {full_url}")
            continue

        # Visit individual asset page
        time.sleep(delay)
        try:
            asset_resp = session.get(full_url, timeout=30)
            asset_resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Failed to load asset page {full_url}: {e}")
            continue

        asset_soup = BeautifulSoup(asset_resp.text, "html.parser")

        # Check for premium content on the detail page
        if is_premium_content(asset_soup):
            logger.info(f"SKIPPED (premium on detail page): {full_url}")
            if url_hash not in history["skipped"]:
                history["skipped"].append(url_hash)
            continue

        # For vehicles: only accept Add-On vehicles (they come with dlc.rpf)
        if asset_type == "vehicles":
            page_text = asset_soup.get_text().lower()
            title_text = (asset_soup.select_one("h1, .mod-title, title") or asset_soup).get_text().lower()
            tag_texts = [t.get_text(strip=True).lower() for t in asset_soup.select(".tag, .mod-tag, a[href*='tag']")]
            is_addon = "add-on" in tag_texts or "addon" in tag_texts or "add-on" in title_text or "addon" in title_text
            has_dlc_mention = "dlc.rpf" in page_text or "dlc rpf" in page_text
            if not is_addon and not has_dlc_mention:
                logger.info(f"SKIPPED (not an Add-On vehicle): {full_url}")
                continue

        # Extract asset name
        title_el = asset_soup.select_one("h1, .mod-title, title")
        asset_name = "unknown"
        display_name = "Unknown Asset"
        if title_el:
            display_name = title_el.get_text().strip()
            # Remove site suffix from page title (e.g. " - GTA5-Mods.com")
            display_name = re.sub(r'\s*[-|]\s*GTA5-Mods\.com\s*$', '', display_name).strip()
            asset_name = re.sub(r'[^\w\s-]', '', display_name)
            asset_name = re.sub(r'\s+', '_', asset_name).strip('_')[:80]

        if not asset_name or asset_name == "unknown":
            continue

        # Extract thumbnail
        thumb_path = extract_thumbnail(session, asset_soup, full_url, download_dir, asset_name, logger)

        # Extract detailed info
        asset_info = extract_asset_info(asset_soup, full_url)

        # Find download link - on gta5-mods.com the pattern is /<category>/<slug>/download/<id>
        download_btn = None

        # Strategy 1: look for the specific download URL pattern
        for a in asset_soup.select("a[href]"):
            a_href = a.get("href", "")
            if "/download/" in a_href and re.search(r'/download/\d+', a_href):
                download_btn = a
                break

        # Strategy 2: button-like download links
        if not download_btn:
            download_btn = asset_soup.select_one(
                "a.btn-download, .download-btn a, "
                "a.btn[href*='download'], .btn-primary[href*='download']"
            )

        # Strategy 3: broader search but with text matching
        if not download_btn:
            for a in asset_soup.select("a"):
                a_text = a.get_text().strip().lower()
                a_href = a.get("href", "").lower()
                if a_text == "download" and "premium" not in a_href:
                    download_btn = a
                    break

        if not download_btn:
            logger.debug(f"No download button found on {full_url}")
            continue

        download_href = download_btn.get("href", "")
        if not download_href:
            continue

        download_url = urljoin(full_url, download_href)

        # Double-check: skip anything behind a paywall
        if any(kw in download_url.lower() for kw in ["patreon", "paypal", "buy", "purchase"]):
            logger.info(f"SKIPPED (paid link): {download_url}")
            continue

        # Download the file - gta5-mods.com uses a two-step process:
        # 1. Visit the download interstitial page
        # 2. Extract the actual CDN file link (files.gta5-mods.com)
        logger.info(f"[{count+1}/{max_items}] ({mod_idx+1}/{len(all_mod_urls)}) Downloading: {display_name}")
        time.sleep(delay)

        try:
            # Step 1: visit the download interstitial page
            dl_page_resp = session.get(download_url, timeout=30,
                                       headers={"Referer": full_url})
            dl_page_resp.raise_for_status()

            # Step 2: find the actual file URL on the interstitial page
            actual_file_url = None
            dl_page_soup = BeautifulSoup(dl_page_resp.text, "html.parser")

            # Look for links to files.gta5-mods.com (the CDN)
            for a in dl_page_soup.select("a[href]"):
                href = a.get("href", "")
                if "files.gta5-mods.com" in href:
                    actual_file_url = href
                    break

            if not actual_file_url:
                # Fallback: look for any direct file link pattern
                file_patterns = re.findall(
                    r'(https?://files\.gta5-mods\.com/[^\s"\'<>]+)',
                    dl_page_resp.text
                )
                if file_patterns:
                    actual_file_url = file_patterns[0]

            if not actual_file_url:
                logger.warning(f"Could not find CDN download link for {display_name}")
                continue

            logger.debug(f"CDN URL: {actual_file_url}")

            # Step 3: download the actual file from CDN
            time.sleep(delay)
            dl_resp = session.get(actual_file_url, timeout=120, stream=True,
                                  headers={"Referer": download_url})
            dl_resp.raise_for_status()

            # Verify we're getting an actual file, not an HTML page
            content_type = dl_resp.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                logger.warning(f"CDN returned HTML instead of a file for {display_name}, skipping")
                continue

            # Determine filename
            content_disp = dl_resp.headers.get("Content-Disposition", "")
            if "filename=" in content_disp:
                filename = re.findall(r'filename="?([^";\n]+)"?', content_disp)
                filename = filename[0] if filename else f"{asset_name}.zip"
            else:
                # Try to extract filename from the CDN URL
                cdn_path = urlparse(actual_file_url).path
                cdn_filename = os.path.basename(cdn_path)
                if cdn_filename and "." in cdn_filename:
                    filename = cdn_filename
                else:
                    # Guess extension from content-type
                    ext = ".zip"
                    if "rar" in content_type:
                        ext = ".rar"
                    elif "7z" in content_type or "x-7z" in content_type:
                        ext = ".7z"
                    filename = f"{asset_name}{ext}"

            # Sanitize filename
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            filepath = os.path.join(download_dir, filename)

            # Don't re-download existing files
            if os.path.exists(filepath):
                logger.info(f"File already exists: {filepath}")
                history["downloaded"].append(url_hash)
                continue

            total_size = int(dl_resp.headers.get("content-length", 0))
            with open(filepath, "wb") as f:
                with tqdm(total=total_size, unit="B", unit_scale=True, desc=filename[:40]) as pbar:
                    for chunk in dl_resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            actual_size = os.path.getsize(filepath)

            # Save metadata for preview dashboard
            asset_metadata = {
                "id": url_hash,
                "name": display_name,
                "safe_name": asset_name,
                "category": asset_type,
                "source_url": full_url,
                "download_url": download_url,
                "filename": filename,
                "filepath": filepath,
                "filesize_bytes": actual_size,
                "filesize_mb": round(actual_size / (1024 * 1024), 2),
                "thumbnail": thumb_path,
                "thumbnail_relative": os.path.relpath(thumb_path, ROOT_DIR) if thumb_path else None,
                "screenshots": asset_info.get("screenshots", []),
                "author": asset_info.get("author", ""),
                "description": asset_info.get("description", ""),
                "tags": asset_info.get("tags", []),
                "downloads_count": asset_info.get("downloads_count", ""),
                "downloaded_at": datetime.now().isoformat(),
                "status": "downloaded"
            }

            asset_index["assets"].append(asset_metadata)

            downloaded_files.append(filepath)
            history["downloaded"].append(url_hash)
            count += 1
            logger.info(f"  Saved: {filename} ({asset_metadata['filesize_mb']} MB)")

        except requests.RequestException as e:
            logger.error(f"Download failed for {download_url}: {e}")
            continue

    return downloaded_files


def main():
    parser = argparse.ArgumentParser(description="RageMP Asset Scraper")
    parser.add_argument("--category", "-c", help="Specific category to scrape")
    parser.add_argument("--count", "-n", type=int, help="Override max download count")
    args = parser.parse_args()

    config = load_config()
    logger = setup_logging(config)
    history = load_download_history()
    asset_index = load_asset_index()

    logger.info("=" * 60)
    logger.info("RageMP Asset Scraper - Starting")
    logger.info(f"Free-only mode: {config['scraper']['skip_premium']}")
    if args.category:
        logger.info(f"Category filter: {args.category}")
    if args.count:
        logger.info(f"Count override: {args.count}")
    logger.info("=" * 60)

    session = get_session(config)
    all_downloads = []

    for source in config["scraper"]["sources"]:
        if not source.get("free_only", True):
            logger.warning(f"Skipping source {source['name']} - not marked as free_only")
            continue

        # Filter by category if specified
        if args.category and source["type"] != args.category:
            continue

        # Override count if specified
        if args.count:
            source = dict(source)
            source["max_per_run"] = args.count

        logger.info(f"\n--- Processing source: {source['name']} ---")
        downloads = scrape_gta5mods(session, source, config, logger, history, asset_index)
        all_downloads.extend(downloads)
        logger.info(f"Downloaded {len(downloads)} files from {source['name']}")

    save_download_history(history)
    save_asset_index(asset_index)

    logger.info(f"\nTotal downloads this run: {len(all_downloads)}")
    logger.info(f"Total assets in index: {len(asset_index['assets'])}")
    logger.info("Scraper finished.")

    return all_downloads


if __name__ == "__main__":
    main()
