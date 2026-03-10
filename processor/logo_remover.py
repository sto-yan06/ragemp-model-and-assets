"""
Vehicle Brand Logo Remover - Detects and removes manufacturer logos
from vehicle textures using OpenCV inpainting.

Supports two modes:
1. Auto-detect: finds text regions and circular badges via contour/edge analysis
2. Manual regions: accepts [x, y, w, h] regions from the dashboard UI

Usage:
    python logo_remover.py --asset <safe_name>
    python logo_remover.py --input <image> --output <image>
"""

import os
import sys
import json
import shutil
import logging
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIEW_BASE = os.path.join(ROOT_DIR, "downloads", "_previews")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("logo_remover")

# Known vehicle manufacturer brand names for detection
BRAND_NAMES = [
    "BMW", "MERCEDES", "BENZ", "AUDI", "VOLKSWAGEN", "VW",
    "PORSCHE", "FERRARI", "LAMBORGHINI", "BUGATTI", "MASERATI",
    "BENTLEY", "ROLLS", "ROYCE", "JAGUAR", "ROVER",
    "FORD", "CHEVROLET", "CHEVY", "DODGE", "CHRYSLER", "JEEP",
    "TOYOTA", "HONDA", "NISSAN", "LEXUS", "INFINITI", "ACURA",
    "HYUNDAI", "KIA", "GENESIS", "SUBARU", "MAZDA", "MITSUBISHI",
    "VOLVO", "PEUGEOT", "RENAULT",
    "ALFA", "ROMEO", "FIAT",
    "MCLAREN", "ASTON", "MARTIN", "LOTUS", "KOENIGSEGG", "PAGANI",
    "CADILLAC", "LINCOLN", "BUICK",
    "KAWASAKI", "YAMAHA", "SUZUKI", "DUCATI", "HARLEY",
    "TESLA", "AMG",
]


def detect_text_regions(image_np):
    """
    Detect potential text/logo regions using edge detection
    and contour analysis. Returns bounding boxes of likely logo areas.
    Uses strict filtering to avoid false positives on detailed textures.
    """
    if cv2 is None:
        return []

    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if len(image_np.shape) == 3 else image_np.copy()
    h, w = gray.shape[:2]
    img_area = w * h

    # Use bilateral filter to preserve edges while smoothing noise
    smoothed = cv2.bilateralFilter(gray, 9, 75, 75)

    # Edge detection with higher thresholds to reduce noise
    edges = cv2.Canny(smoothed, 80, 200)

    # Connect nearby edges — use moderate kernels to avoid merging everything
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 2))
    dilated = cv2.dilate(edges, kernel_h, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        area_pct = area / img_area

        # Stricter filter: logo/text regions are typically 0.5%–8% of image area
        if area_pct < 0.005 or area_pct > 0.08:
            continue

        # Aspect ratio filter: text is wider than tall (1.5–8)
        aspect = cw / max(ch, 1)
        if aspect < 1.2 or aspect > 8:
            continue

        # Check edge density in ROI — must be moderate (not too dense = texture detail)
        roi = edges[y:y+ch, x:x+cw]
        density = np.count_nonzero(roi) / max(area, 1)
        if density < 0.05 or density > 0.5:
            continue

        # Check that the surrounding area is relatively uniform (logos sit on flat surfaces)
        pad_y = max(0, y - ch)
        pad_x = max(0, x - cw // 2)
        pad_y2 = min(h, y + ch * 2)
        pad_x2 = min(w, x + cw + cw // 2)
        surround = gray[pad_y:pad_y2, pad_x:pad_x2]
        if surround.size > 0:
            surround_std = np.std(surround)
            # If surrounding area is very noisy, this is likely texture detail, not a logo
            if surround_std > 60:
                continue

        regions.append({
            'x': int(x), 'y': int(y), 'w': int(cw), 'h': int(ch),
            'confidence': round(min(density * 3, 1.0), 2),
            'type': 'text'
        })

    return regions


def detect_circular_logos(image_np):
    """Detect circular badge-like features (roundels, emblems).
    Uses strict parameters to avoid detecting wheels, bolts, etc."""
    if cv2 is None:
        return []

    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if len(image_np.shape) == 3 else image_np.copy()
    h, w = gray.shape[:2]

    # Skip small images
    if h < 128 or w < 128:
        return []

    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    # Tighter radius range: logos are typically 2-8% of image dimension
    min_dist = max(max(w, h) // 8, 1)
    min_radius = max(max(w, h) // 30, 8)
    max_radius = max(max(w, h) // 8, min_radius + 1)

    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=min_dist,
        param1=120, param2=60,  # Higher thresholds = fewer false positives
        minRadius=min_radius,
        maxRadius=max_radius
    )

    regions = []
    if circles is not None:
        for circle in circles[0]:
            cx, cy, r = int(circle[0]), int(circle[1]), int(circle[2])
            # Ensure the circle is within bounds with margin
            if cx - r < 5 or cy - r < 5 or cx + r > w - 5 or cy + r > h - 5:
                continue

            # Check that circle interior has significant contrast (actual emblem)
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.circle(mask, (cx, cy), r, 255, -1)
            roi = gray[mask > 0]
            if roi.size > 0:
                roi_std = np.std(roi)
                # Skip if interior is too uniform (not a logo) or too noisy (texture)
                if roi_std < 15 or roi_std > 70:
                    continue

            regions.append({
                'x': cx - r, 'y': cy - r, 'w': 2 * r, 'h': 2 * r,
                'type': 'circular', 'radius': int(r),
                'confidence': 0.6
            })

    return regions


def detect_high_contrast_regions(image_np):
    """
    Find small high-contrast regions that could be embossed logos,
    badges, or watermarks on relatively uniform surfaces.
    Very conservative to avoid destroying texture detail.
    """
    if cv2 is None:
        return []

    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if len(image_np.shape) == 3 else image_np.copy()
    h, w = gray.shape[:2]

    # Skip small textures entirely
    if h < 256 or w < 256:
        return []

    # Local contrast via Laplacian
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    abs_lap = np.abs(laplacian).astype(np.uint8)

    # Higher threshold to only catch sharp isolated features
    _, thresh = cv2.threshold(abs_lap, 50, 255, cv2.THRESH_BINARY)

    # Morphological cleanup — smaller kernel to avoid merging nearby details
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    img_area = w * h
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        area_pct = area / img_area

        # Tighter range: 1%-5% of image
        if area_pct < 0.01 or area_pct > 0.05:
            continue

        # Prefer roughly square regions (logos tend to be compact)
        aspect = cw / max(ch, 1)
        if aspect < 0.5 or aspect > 2.5:
            continue

        # Verify the region sits on a relatively uniform background
        # Expand region and check surrounding uniformity
        pad = max(cw, ch)
        sx = max(0, x - pad)
        sy = max(0, y - pad)
        sx2 = min(w, x + cw + pad)
        sy2 = min(h, y + ch + pad)
        surround = gray[sy:sy2, sx:sx2]
        if surround.size > 0 and np.std(surround) > 50:
            continue  # Too noisy surroundings — not a logo on a flat surface

        regions.append({
            'x': int(x), 'y': int(y), 'w': int(cw), 'h': int(ch),
            'type': 'contrast', 'confidence': 0.4
        })

    return regions


def merge_overlapping_regions(regions, overlap_thresh=0.3):
    """Merge regions that overlap significantly."""
    if not regions:
        return []

    merged = []
    used = set()

    for i, r1 in enumerate(regions):
        if i in used:
            continue
        x1, y1 = r1['x'], r1['y']
        x2, y2 = x1 + r1['w'], y1 + r1['h']

        for j, r2 in enumerate(regions):
            if j <= i or j in used:
                continue
            rx1, ry1 = r2['x'], r2['y']
            rx2, ry2 = rx1 + r2['w'], ry1 + r2['h']

            # Check overlap
            ix1, iy1 = max(x1, rx1), max(y1, ry1)
            ix2, iy2 = min(x2, rx2), min(y2, ry2)
            if ix1 < ix2 and iy1 < iy2:
                inter = (ix2 - ix1) * (iy2 - iy1)
                area1 = r1['w'] * r1['h']
                area2 = r2['w'] * r2['h']
                overlap = inter / min(area1, area2)
                if overlap > overlap_thresh:
                    # Merge: expand to union
                    x1 = min(x1, rx1)
                    y1 = min(y1, ry1)
                    x2 = max(x2, rx2)
                    y2 = max(y2, ry2)
                    used.add(j)

        merged.append({
            'x': x1, 'y': y1, 'w': x2 - x1, 'h': y2 - y1,
            'type': r1.get('type', 'merged'),
            'confidence': max(r1.get('confidence', 0.5),
                              max((r.get('confidence', 0) for r in regions if regions.index(r) in used), default=0))
        })
        used.add(i)

    return merged


def create_inpaint_mask(shape, regions, padding=8):
    """Create a binary mask from detected regions with padding."""
    mask = np.zeros(shape[:2], dtype=np.uint8)
    h, w = shape[:2]

    for region in regions:
        x = max(0, region['x'] - padding)
        y = max(0, region['y'] - padding)
        x2 = min(w, region['x'] + region['w'] + padding)
        y2 = min(h, region['y'] + region['h'] + padding)

        if region.get('type') == 'circular' and 'radius' in region:
            cx = region['x'] + region['w'] // 2
            cy = region['y'] + region['h'] // 2
            cv2.circle(mask, (cx, cy), region['radius'] + padding, 255, -1)
        else:
            # Use rounded rectangle for cleaner inpainting
            mask[y:y2, x:x2] = 255

    return mask


def remove_logos(image_np, regions, method='hybrid', inpaint_radius=8):
    """Apply inpainting to remove detected logo regions.
    Uses a hybrid approach: NS for structure, then TELEA for smoothing."""
    if not regions:
        return image_np.copy()

    mask = create_inpaint_mask(image_np.shape, regions, padding=12)

    if method == 'hybrid':
        # First pass: Navier-Stokes for structural coherence
        pass1 = cv2.inpaint(image_np, mask, inpaint_radius, cv2.INPAINT_NS)
        # Second pass: TELEA on the already-inpainted result for smoother blending
        # Use a smaller mask (eroded) for refinement
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        refined_mask = cv2.erode(mask, kernel, iterations=1)
        if np.count_nonzero(refined_mask) > 0:
            pass2 = cv2.inpaint(pass1, refined_mask, inpaint_radius // 2, cv2.INPAINT_TELEA)
            return pass2
        return pass1
    elif method == 'telea':
        return cv2.inpaint(image_np, mask, inpaint_radius, cv2.INPAINT_TELEA)
    return cv2.inpaint(image_np, mask, inpaint_radius, cv2.INPAINT_NS)


# Texture names that are PRIMARY logo targets — use aggressive detection
LOGO_TEXTURE_PATTERNS = [
    'sign', 'livery', 'logo', 'badge', 'emblem', 'brand',
    'decal', 'label', 'plate', 'nameplate', 'calliperbadge',
]

# Texture names that should NEVER be processed (would destroy detail)
SKIP_TEXTURE_PATTERNS = [
    '_n.', '_nm.', '_nrm', '_nrml', '_normal', '_bump',
    '_s.', '_spec', '_material', '_o.',
    'ao_', 'emissive', '_e.',
]


def should_process_texture(filename):
    """Determine if a texture file is likely to contain removable logos."""
    lower = filename.lower()

    # Skip normal maps, specular maps, etc.
    for skip in SKIP_TEXTURE_PATTERNS:
        if skip in lower:
            return False

    # Always process textures explicitly named as logos
    for pattern in LOGO_TEXTURE_PATTERNS:
        if pattern in lower:
            return 'aggressive'

    # Process all diffuse textures (various naming conventions)
    if any(s in lower for s in ['_d.', '_diff', '_diffuse', '_tex.']):
        return True

    return False


def detect_text_regions_aggressive(image_np):
    """
    Aggressive text/logo detection for textures explicitly named as logos.
    Lower thresholds, wider aspect ratios, no surrounding uniformity check.
    """
    if cv2 is None:
        return []

    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if len(image_np.shape) == 3 else image_np.copy()
    h, w = gray.shape[:2]
    img_area = w * h

    # Light smoothing only
    smoothed = cv2.GaussianBlur(gray, (5, 5), 1)

    # Lower Canny thresholds to catch more edges
    edges = cv2.Canny(smoothed, 40, 120)

    # Connect nearby edges aggressively
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5))
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 20))
    dilated_h = cv2.dilate(edges, kernel_h, iterations=2)
    dilated_v = cv2.dilate(edges, kernel_v, iterations=2)
    dilated = cv2.bitwise_or(dilated_h, dilated_v)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        area_pct = area / img_area

        # Wide range: 1% to 50% of image
        if area_pct < 0.01 or area_pct > 0.50:
            continue

        # Very wide aspect ratio range
        aspect = cw / max(ch, 1)
        if aspect < 0.2 or aspect > 12:
            continue

        # Edge density check
        roi = edges[y:y+ch, x:x+cw]
        density = np.count_nonzero(roi) / max(area, 1)
        if density < 0.02:
            continue

        regions.append({
            'x': int(x), 'y': int(y), 'w': int(cw), 'h': int(ch),
            'confidence': round(min(density * 4, 1.0), 2),
            'type': 'text_aggressive'
        })

    return regions


def detect_circular_logos_aggressive(image_np):
    """Aggressive circular detection for logo textures. Lower thresholds."""
    if cv2 is None:
        return []

    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY) if len(image_np.shape) == 3 else image_np.copy()
    h, w = gray.shape[:2]

    if h < 32 or w < 32:
        return []

    blurred = cv2.GaussianBlur(gray, (7, 7), 2)

    min_dist = max(max(w, h) // 6, 1)
    min_radius = max(max(w, h) // 20, 5)
    max_radius = max(max(w, h) // 3, min_radius + 1)

    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=min_dist,
        param1=80, param2=35,
        minRadius=min_radius,
        maxRadius=max_radius
    )

    regions = []
    if circles is not None:
        for circle in circles[0]:
            cx, cy, r = int(circle[0]), int(circle[1]), int(circle[2])
            if cx - r < 0 or cy - r < 0 or cx + r > w or cy + r > h:
                continue
            regions.append({
                'x': max(0, cx - r), 'y': max(0, cy - r),
                'w': min(2 * r, w), 'h': min(2 * r, h),
                'type': 'circular', 'radius': int(r),
                'confidence': 0.7
            })

    return regions


def process_single_texture(input_path, output_path, custom_regions=None):
    """Process one texture: detect logos, remove them, save result."""
    if cv2 is None:
        logger.error("OpenCV not installed. Run: pip install opencv-python-headless")
        return None

    filename = os.path.basename(input_path)

    # Check if this texture should be processed
    process_mode = should_process_texture(filename) if not custom_regions else True
    if not process_mode:
        logger.info(f"  Skipping (not a logo texture): {filename}")
        shutil.copy2(input_path, output_path)
        return {
            'file': filename,
            'regions': [],
            'modified': False
        }

    img = cv2.imread(input_path)
    if img is None:
        logger.warning(f"Could not load: {input_path}")
        return None

    aggressive = (process_mode == 'aggressive')

    # Auto-detect logo regions
    all_regions = []
    if custom_regions:
        all_regions = custom_regions
    elif aggressive:
        # Logo-named textures: use ALL detectors with aggressive settings
        logger.info(f"  Aggressive scan: {filename}")
        text_r = detect_text_regions_aggressive(img)
        circle_r = detect_circular_logos_aggressive(img)
        contrast_r = detect_high_contrast_regions(img)
        # Also run standard detectors
        text_r2 = detect_text_regions(img)
        circle_r2 = detect_circular_logos(img)
        all_regions = merge_overlapping_regions(
            text_r + circle_r + contrast_r + text_r2 + circle_r2
        )
        # Lower confidence threshold for logo textures
        all_regions = [r for r in all_regions if r.get('confidence', 0) >= 0.15]
    else:
        # Standard diffuse textures: use all detectors
        text_r = detect_text_regions(img)
        circle_r = detect_circular_logos(img)
        contrast_r = detect_high_contrast_regions(img)
        all_regions = merge_overlapping_regions(text_r + circle_r + contrast_r)
        all_regions = [r for r in all_regions if r.get('confidence', 0) >= 0.3]

    if not all_regions:
        logger.info(f"  No logos found: {filename}")
        shutil.copy2(input_path, output_path)
        return {
            'file': filename,
            'regions': [],
            'modified': False
        }

    # Apply hybrid inpainting for better quality
    result = remove_logos(img, all_regions, method='hybrid')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, result)

    logger.info(f"  Cleaned: {filename} "
                f"({len(all_regions)} region(s) removed)")

    return {
        'file': filename,
        'regions': all_regions,
        'modified': True
    }


def process_asset_textures(safe_name, custom_regions_map=None):
    """Process all extracted textures for an asset."""
    preview_dir = os.path.join(PREVIEW_BASE, safe_name)
    textures_dir = os.path.join(preview_dir, "textures")
    cleaned_dir = os.path.join(preview_dir, "logo_cleaned")

    if not os.path.exists(textures_dir):
        logger.error(f"No textures directory for {safe_name}. Run extract_preview.py first.")
        return []

    os.makedirs(cleaned_dir, exist_ok=True)

    results = []
    for f in sorted(os.listdir(textures_dir)):
        if not f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            continue

        input_path = os.path.join(textures_dir, f)
        output_path = os.path.join(cleaned_dir, f)

        custom = None
        if custom_regions_map and f in custom_regions_map:
            custom = custom_regions_map[f]

        result = process_single_texture(input_path, output_path, custom)
        if result:
            results.append(result)

    # Save results summary
    summary_path = os.path.join(preview_dir, "logo_removal.json")
    with open(summary_path, "w") as f:
        json.dump({
            'processed_at': __import__('datetime').datetime.now().isoformat(),
            'total': len(results),
            'modified': sum(1 for r in results if r['modified']),
            'files': results
        }, f, indent=2, default=str)

    return results


def main():
    import argparse
    import shutil

    parser = argparse.ArgumentParser(description="Remove vehicle brand logos from textures")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--asset", help="Asset safe_name to process")
    group.add_argument("--input", help="Single image file to process")
    parser.add_argument("--output", help="Output path (for --input mode)")
    parser.add_argument("--regions", help="JSON string of custom regions [{x,y,w,h}, ...]")
    args = parser.parse_args()

    if args.input:
        output = args.output or args.input.replace('.', '_cleaned.')
        custom = json.loads(args.regions) if args.regions else None
        result = process_single_texture(args.input, output, custom)
        print(json.dumps(result or {'error': 'failed'}, default=str))
    else:
        custom_map = None
        if args.regions:
            custom_map = json.loads(args.regions)
        results = process_asset_textures(args.asset, custom_map)
        modified = sum(1 for r in results if r['modified'])
        print(json.dumps({
            'total': len(results),
            'modified': modified,
            'files': [{
                'file': r['file'],
                'modified': r['modified'],
                'regions_count': len(r['regions'])
            } for r in results]
        }, default=str))


if __name__ == "__main__":
    main()
