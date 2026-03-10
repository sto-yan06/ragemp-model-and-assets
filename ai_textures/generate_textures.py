"""
AI Texture Generator - Uses Stable Diffusion (via AUTOMATIC1111 API) to generate
texture variations for GTA V assets.

Requirements:
- Stable Diffusion WebUI running with --api flag
- Default endpoint: http://127.0.0.1:7860

This generates tileable textures that can later be converted to .ytd format.
"""

import os
import sys
import json
import base64
import logging
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
PROMPTS_PATH = os.path.join(os.path.dirname(__file__), "prompts.json")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def load_prompts():
    with open(PROMPTS_PATH, "r") as f:
        return json.load(f)


def setup_logging(config):
    log_dir = config.get("logging", {}).get("log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"ai_textures_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=getattr(logging, config.get("logging", {}).get("level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("ai_textures")


def check_sd_api(api_url, logger):
    """Check if Stable Diffusion API is available."""
    try:
        resp = requests.get(f"{api_url}/sdapi/v1/sd-models", timeout=10)
        resp.raise_for_status()
        models = resp.json()
        logger.info(f"SD API connected. Available models: {len(models)}")
        return True
    except Exception as e:
        logger.error(f"Stable Diffusion API not available at {api_url}: {e}")
        logger.info("Make sure AUTOMATIC1111 WebUI is running with --api flag")
        return False


def generate_texture(api_url, prompt_data, width, height, batch_size, logger):
    """Generate textures using Stable Diffusion txt2img API."""
    payload = {
        "prompt": prompt_data["prompt"],
        "negative_prompt": prompt_data.get("negative_prompt", ""),
        "steps": 30,
        "cfg_scale": 7.5,
        "width": width,
        "height": height,
        "batch_size": batch_size,
        "sampler_name": "DPM++ 2M Karras",
        "seed": -1,
        "tiling": True  # Important for seamless textures
    }

    try:
        resp = requests.post(f"{api_url}/sdapi/v1/txt2img", json=payload, timeout=300)
        resp.raise_for_status()
        result = resp.json()

        images = []
        for i, img_data in enumerate(result.get("images", [])):
            img_bytes = base64.b64decode(img_data)
            img = Image.open(BytesIO(img_bytes))
            images.append(img)

        logger.info(f"Generated {len(images)} textures for '{prompt_data['name']}'")
        return images

    except requests.Timeout:
        logger.error(f"Timeout generating texture for '{prompt_data['name']}'")
        return []
    except Exception as e:
        logger.error(f"Error generating texture for '{prompt_data['name']}': {e}")
        return []


def save_textures(images, name, output_dir, logger):
    """Save generated texture images as PNG files."""
    saved = []
    for i, img in enumerate(images):
        filename = f"{name}_{i:03d}.png"
        filepath = os.path.join(output_dir, filename)
        img.save(filepath, "PNG")
        saved.append(filepath)
        logger.debug(f"Saved: {filepath}")
    return saved


def create_texture_sheet(images, name, output_dir, logger):
    """Create a texture atlas/sheet from multiple variations."""
    if len(images) < 4:
        return None

    # Create a 2x2 grid
    w, h = images[0].size
    sheet = Image.new("RGB", (w * 2, h * 2))
    for i, img in enumerate(images[:4]):
        x = (i % 2) * w
        y = (i // 2) * h
        sheet.paste(img.resize((w, h)), (x, y))

    filepath = os.path.join(output_dir, f"{name}_sheet.png")
    sheet.save(filepath, "PNG")
    logger.info(f"Created texture sheet: {filepath}")
    return filepath


def main():
    config = load_config()
    logger = setup_logging(config)
    ai_config = config["ai_textures"]

    logger.info("=" * 60)
    logger.info("AI Texture Generator - Starting")
    logger.info("=" * 60)

    if not ai_config.get("enabled", False):
        logger.warning("AI texture generation is disabled in config.")
        logger.info("Set ai_textures.enabled to true and ensure Stable Diffusion is running.")
        return

    api_url = ai_config["stable_diffusion_api"]
    output_dir = ai_config["output_dir"]
    width = ai_config.get("width", 1024)
    height = ai_config.get("height", 1024)
    batch_size = ai_config.get("batch_size", 4)

    os.makedirs(output_dir, exist_ok=True)

    if not check_sd_api(api_url, logger):
        return

    prompts = load_prompts()
    all_generated = []

    for category, prompt_list in prompts.items():
        category_dir = os.path.join(output_dir, category)
        os.makedirs(category_dir, exist_ok=True)

        logger.info(f"\n--- Generating {category} textures ---")

        for prompt_data in prompt_list:
            logger.info(f"Generating: {prompt_data['name']}")
            images = generate_texture(api_url, prompt_data, width, height, batch_size, logger)

            if images:
                saved = save_textures(images, prompt_data["name"], category_dir, logger)
                all_generated.extend(saved)

                # Create texture sheet if enough images
                create_texture_sheet(images, prompt_data["name"], category_dir, logger)

    # Generate summary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_textures": len(all_generated),
        "files": all_generated
    }

    summary_path = os.path.join(output_dir, "generation_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"\nTotal textures generated: {len(all_generated)}")
    logger.info("AI texture generation complete.")


if __name__ == "__main__":
    main()
