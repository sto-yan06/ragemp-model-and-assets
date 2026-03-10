"""
AI Variation Generator - Multiplies a single asset into many variants.

Example: 1 vehicle model → 20 paint textures × 5 wheel variants = 100 variations

Works by:
1. Taking a base texture
2. Generating color/style variations via Stable Diffusion img2img
3. Saving each variant for GTA conversion
"""

import os
import sys
import json
import base64
import logging
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def setup_logging(config):
    log_dir = config.get("logging", {}).get("log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"variations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("variation_gen")


# ── Non-AI color variations (no Stable Diffusion needed) ──

COLOR_PRESETS = {
    "police_white": {"hue_shift": 0, "saturation": 0.0, "brightness": 1.3},
    "taxi_yellow": {"hue_shift": 45, "saturation": 1.8, "brightness": 1.1},
    "fire_red": {"hue_shift": 0, "saturation": 1.5, "brightness": 0.9},
    "midnight_blue": {"hue_shift": 220, "saturation": 1.2, "brightness": 0.5},
    "forest_green": {"hue_shift": 120, "saturation": 1.3, "brightness": 0.7},
    "hot_pink": {"hue_shift": 320, "saturation": 1.6, "brightness": 1.0},
    "sunset_orange": {"hue_shift": 30, "saturation": 1.5, "brightness": 1.0},
    "stealth_grey": {"hue_shift": 0, "saturation": 0.1, "brightness": 0.6},
    "gold_metallic": {"hue_shift": 50, "saturation": 1.4, "brightness": 1.2},
    "purple_haze": {"hue_shift": 280, "saturation": 1.3, "brightness": 0.8},
    "arctic_white": {"hue_shift": 0, "saturation": 0.0, "brightness": 1.5},
    "deep_black": {"hue_shift": 0, "saturation": 0.0, "brightness": 0.2},
    "army_olive": {"hue_shift": 80, "saturation": 0.6, "brightness": 0.6},
    "rust_brown": {"hue_shift": 20, "saturation": 0.8, "brightness": 0.5},
    "electric_blue": {"hue_shift": 200, "saturation": 1.8, "brightness": 1.0},
    "lime_green": {"hue_shift": 90, "saturation": 1.8, "brightness": 1.1},
    "burgundy": {"hue_shift": 345, "saturation": 1.2, "brightness": 0.5},
    "cream": {"hue_shift": 40, "saturation": 0.3, "brightness": 1.3},
    "teal": {"hue_shift": 175, "saturation": 1.2, "brightness": 0.8},
    "copper": {"hue_shift": 25, "saturation": 1.0, "brightness": 0.7},
}


def apply_color_variation(image, preset_name, preset_values):
    """Apply a color variation to a texture using PIL (no AI needed)."""
    img = image.copy()

    # Convert to HSV-like manipulation
    hsv = img.convert("HSV")
    h, s, v = hsv.split()

    # Adjust brightness
    brightness = preset_values.get("brightness", 1.0)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(brightness)

    # Adjust saturation
    saturation = preset_values.get("saturation", 1.0)
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(saturation)

    # Hue shift via color overlay
    hue_shift = preset_values.get("hue_shift", 0)
    if hue_shift > 0:
        hsv_img = img.convert("HSV")
        h, s, v = hsv_img.split()
        h = h.point(lambda p: (p + hue_shift) % 256)
        hsv_img = Image.merge("HSV", (h, s, v))
        img = hsv_img.convert("RGB")

    return img


def apply_weathering(image, intensity=0.5):
    """Apply a weathering/aging effect."""
    img = image.copy()

    # Reduce saturation
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.0 - intensity * 0.5)

    # Slightly blur
    if intensity > 0.3:
        img = img.filter(ImageFilter.GaussianBlur(radius=intensity))

    # Reduce contrast slightly
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.0 - intensity * 0.3)

    return img


def generate_ai_variation(api_url, base_image, prompt, logger):
    """Generate a variation using Stable Diffusion img2img API."""
    # Encode base image
    buffer = BytesIO()
    base_image.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    payload = {
        "init_images": [img_base64],
        "prompt": prompt,
        "negative_prompt": "text, watermark, logo, blurry",
        "steps": 25,
        "cfg_scale": 7.0,
        "denoising_strength": 0.5,
        "width": base_image.width,
        "height": base_image.height,
        "sampler_name": "DPM++ 2M Karras",
        "seed": -1
    }

    try:
        resp = requests.post(f"{api_url}/sdapi/v1/img2img", json=payload, timeout=300)
        resp.raise_for_status()
        result = resp.json()

        images = []
        for img_data in result.get("images", []):
            img_bytes = base64.b64decode(img_data)
            img = Image.open(BytesIO(img_bytes))
            images.append(img)
        return images

    except Exception as e:
        logger.error(f"AI variation failed: {e}")
        return []


def process_texture_file(input_path, output_dir, config, logger, use_ai=False):
    """Generate all variations for a single texture file."""
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    logger.info(f"Generating variations for: {base_name}")

    base_image = Image.open(input_path)
    generated = []

    # 1. Color variations (no AI needed)
    for preset_name, preset_values in COLOR_PRESETS.items():
        variant = apply_color_variation(base_image, preset_name, preset_values)
        filename = f"{base_name}_{preset_name}.png"
        filepath = os.path.join(output_dir, filename)
        variant.save(filepath, "PNG")
        generated.append(filepath)

    # 2. Weathered variations
    for intensity_name, intensity in [("light_wear", 0.3), ("medium_wear", 0.5), ("heavy_wear", 0.8)]:
        variant = apply_weathering(base_image, intensity)
        filename = f"{base_name}_{intensity_name}.png"
        filepath = os.path.join(output_dir, filename)
        variant.save(filepath, "PNG")
        generated.append(filepath)

    # 3. AI variations (if Stable Diffusion is available)
    if use_ai:
        api_url = config["ai_textures"]["stable_diffusion_api"]
        ai_prompts = [
            "racing car paint texture, glossy, metallic flakes",
            "military camouflage texture, realistic",
            "carbon fiber weave texture, dark",
            "rusty weathered metal texture, corroded",
            "custom graffiti painted texture, urban street art style"
        ]
        for i, prompt in enumerate(ai_prompts):
            variants = generate_ai_variation(api_url, base_image, prompt, logger)
            for j, variant in enumerate(variants):
                filename = f"{base_name}_ai_{i}_{j}.png"
                filepath = os.path.join(output_dir, filename)
                variant.save(filepath, "PNG")
                generated.append(filepath)

    logger.info(f"  Generated {len(generated)} variations for {base_name}")
    return generated


def main():
    config = load_config()
    logger = setup_logging(config)

    logger.info("=" * 60)
    logger.info("AI Variation Generator - Starting")
    logger.info("=" * 60)

    input_dir = os.path.join("assets", "textures")
    output_dir = os.path.join("ai_textures", "variations")
    os.makedirs(output_dir, exist_ok=True)

    use_ai = config["ai_textures"].get("enabled", False)
    if not use_ai:
        logger.info("AI mode disabled - generating color variations only (no Stable Diffusion needed)")

    # Find all texture files
    texture_files = []
    if os.path.exists(input_dir):
        for f in os.listdir(input_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tga")):
                texture_files.append(os.path.join(input_dir, f))

    if not texture_files:
        logger.warning(f"No texture files found in {input_dir}")
        logger.info("Place .png/.jpg texture files in the assets/textures directory")
        return

    all_generated = []
    for tex_path in texture_files:
        generated = process_texture_file(tex_path, output_dir, config, logger, use_ai)
        all_generated.extend(generated)

    # Summary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "input_textures": len(texture_files),
        "total_variations": len(all_generated),
        "ai_enabled": use_ai,
        "files": all_generated
    }

    summary_path = os.path.join(output_dir, "variation_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"\nInput textures: {len(texture_files)}")
    logger.info(f"Total variations generated: {len(all_generated)}")
    logger.info(f"Multiplication factor: {len(all_generated) / max(len(texture_files), 1):.0f}x")
    logger.info("Variation generation complete.")


if __name__ == "__main__":
    main()
