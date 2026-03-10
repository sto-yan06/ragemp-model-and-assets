"""
Asset Preview Extractor - Extracts downloaded archives and prepares
textures and 3D models for the web preview dashboard.

Handles:
- .zip and .7z archive extraction
- DDS/TGA texture conversion to PNG for web display
- 3D model conversion (OBJ/FBX → GLB) via trimesh
- CodeWalker integration for RPF/YFT export (if available)
- File manifest generation for the dashboard

Usage:
    python extract_preview.py --asset-id <id>
    python extract_preview.py --all
"""

import os
import sys
import json
import zipfile
import shutil
import logging
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import py7zr
except ImportError:
    py7zr = None

try:
    import rarfile
except ImportError:
    rarfile = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import trimesh
except ImportError:
    trimesh = None

try:
    from gta_converter.rpf_parser import RPFFile
    from gta_converter.ytd_parser import extract_textures_from_ytd
    from gta_converter.yft_parser import extract_model_from_yft
    import struct, zlib
    HAS_RPF_PARSER = True
except ImportError:
    HAS_RPF_PARSER = False

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
INDEX_PATH = os.path.join(ROOT_DIR, "downloads", "_metadata", "asset_index.json")
PREVIEW_BASE = os.path.join(ROOT_DIR, "downloads", "_previews")

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds', '.gif'}
MODEL_EXTS = {'.obj', '.fbx', '.gltf', '.glb', '.dae', '.stl', '.ply'}
GTA_EXTS = {'.yft', '.ytd', '.ydr', '.ydd', '.ymap', '.ytyp'}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("extract_preview")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_index():
    with open(INDEX_PATH) as f:
        return json.load(f)


def save_index(data):
    with open(INDEX_PATH, "w") as f:
        json.dump(data, f, indent=2)


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def extract_archive(archive_path, output_dir):
    """Extract .zip or .7z archive safely."""
    os.makedirs(output_dir, exist_ok=True)
    lower = archive_path.lower()

    if lower.endswith('.zip'):
        try:
            with zipfile.ZipFile(archive_path, 'r') as z:
                for member in z.namelist():
                    member_path = os.path.realpath(os.path.join(output_dir, member))
                    if not member_path.startswith(os.path.realpath(output_dir)):
                        logger.warning(f"Skipping path traversal attempt: {member}")
                        continue
                z.extractall(output_dir)
            return True
        except zipfile.BadZipFile:
            logger.error(f"Bad zip file: {archive_path}")
            return False

    elif lower.endswith('.7z'):
        if py7zr is None:
            logger.error("py7zr not installed. Run: pip install py7zr")
            return False
        try:
            with py7zr.SevenZipFile(archive_path, 'r') as z:
                z.extractall(output_dir)
            return True
        except Exception as e:
            logger.error(f"7z extraction failed: {e}")
            return False

    elif lower.endswith('.rar'):
        # Try 7-Zip first (most reliable for RAR5 on Windows)
        seven_zip_paths = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            "7z",
        ]
        for sz_path in seven_zip_paths:
            try:
                result = subprocess.run(
                    [sz_path, "x", "-y", f"-o{output_dir}", archive_path],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode == 0:
                    return True
                logger.debug(f"7z returned code {result.returncode}: {result.stderr[:200]}")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        # Fallback: rarfile library
        if rarfile is not None:
            try:
                with rarfile.RarFile(archive_path, 'r') as z:
                    z.extractall(output_dir)
                return True
            except Exception as e:
                logger.error(f"RAR extraction failed: {e}")
                return False

        logger.error("No RAR extractor available. Install 7-Zip or unrar.")
        return False

    logger.warning(f"Unsupported archive: {archive_path}")
    return False


def categorize_files(directory):
    """Walk directory and categorize all files by type."""
    result = {
        'images': [], 'models': [], 'gta_files': [],
        'rpf_files': [], 'meta_files': [], 'other': [], 'all': []
    }

    for root, _, files in os.walk(directory):
        for f in files:
            filepath = os.path.join(root, f)
            relpath = os.path.relpath(filepath, directory)
            ext = os.path.splitext(f)[1].lower()

            try:
                size = os.path.getsize(filepath)
            except OSError:
                continue

            entry = {
                'path': relpath.replace('\\', '/'),
                'name': f,
                'ext': ext,
                'size': size,
                'size_display': format_size(size),
                'full_path': filepath
            }

            result['all'].append(entry)

            if ext in IMAGE_EXTS:
                result['images'].append(entry)
            elif ext in MODEL_EXTS:
                result['models'].append(entry)
            elif ext in GTA_EXTS:
                result['gta_files'].append(entry)
            elif ext == '.rpf':
                result['rpf_files'].append(entry)
            elif ext in {'.meta', '.xml', '.txt', '.ini', '.cfg', '.md'}:
                result['meta_files'].append(entry)
            else:
                result['other'].append(entry)

    return result


def convert_texture_to_png(input_path, output_path):
    """Convert DDS/TGA/BMP texture to PNG for web display."""
    if Image is None:
        return False
    try:
        img = Image.open(input_path)
        if img.mode == 'P':
            img = img.convert('RGBA')
        elif img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA')
        img.save(output_path, "PNG")
        logger.info(f"  Texture: {os.path.basename(input_path)} → PNG ({img.size[0]}×{img.size[1]})")
        return True
    except Exception as e:
        logger.warning(f"  Failed to convert {os.path.basename(input_path)}: {e}")
        return False


def convert_model_to_glb(input_path, output_path):
    """Convert OBJ/FBX/DAE to GLB using trimesh."""
    if trimesh is None:
        return False
    try:
        scene = trimesh.load(input_path)
        scene.export(output_path, file_type='glb')
        logger.info(f"  Model: {os.path.basename(input_path)} → GLB")
        return True
    except Exception as e:
        logger.warning(f"  Failed to convert {os.path.basename(input_path)}: {e}")
        return False


def try_codewalker_extract(rpf_path, output_dir, config):
    """Try to use CodeWalker CLI to extract RPF contents."""
    cw_path = config.get("converter", {}).get("codewalker_path", "")
    if not cw_path or not os.path.exists(cw_path):
        return False

    cw_exe = os.path.join(cw_path, "CodeWalker.exe")
    if not os.path.exists(cw_exe):
        return False

    os.makedirs(output_dir, exist_ok=True)
    try:
        result = subprocess.run(
            [cw_exe, "-extract", rpf_path, "-output", output_dir],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and os.listdir(output_dir):
            logger.info(f"  CodeWalker extracted RPF: {os.path.basename(rpf_path)}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"  CodeWalker extraction failed: {e}")
    return False


def process_extracted_files(files, textures_dir, models_dir):
    """Process categorized files: convert textures and models."""
    converted_textures = []
    converted_models = []

    for img in files['images']:
        ext = img['ext']
        basename = os.path.splitext(img['name'])[0]

        if ext in {'.png', '.jpg', '.jpeg', '.gif'}:
            dst = os.path.join(textures_dir, img['name'])
            if not os.path.exists(dst):
                shutil.copy2(img['full_path'], dst)
            converted_textures.append({
                'name': img['name'], 'original': img['path'],
                'preview': f"textures/{img['name']}", 'format': ext[1:].upper(),
                'width': 0, 'height': 0
            })
        elif ext in {'.dds', '.tga', '.bmp'}:
            png_name = f"{basename}.png"
            dst = os.path.join(textures_dir, png_name)
            if convert_texture_to_png(img['full_path'], dst):
                converted_textures.append({
                    'name': png_name, 'original': img['path'],
                    'original_name': img['name'],
                    'preview': f"textures/{png_name}", 'format': ext[1:].upper()
                })

    for model in files['models']:
        ext = model['ext']
        basename = os.path.splitext(model['name'])[0]

        if ext in {'.glb', '.gltf'}:
            dst = os.path.join(models_dir, model['name'])
            shutil.copy2(model['full_path'], dst)
            converted_models.append({
                'name': model['name'], 'path': f"models/{model['name']}",
                'format': ext[1:].upper()
            })
        elif ext in {'.obj', '.fbx', '.dae', '.stl'}:
            glb_name = f"{basename}.glb"
            dst = os.path.join(models_dir, glb_name)
            if convert_model_to_glb(model['full_path'], dst):
                converted_models.append({
                    'name': glb_name, 'original_name': model['name'],
                    'path': f"models/{glb_name}", 'format': 'GLB'
                })

    return converted_textures, converted_models


def extract_preview_for_asset(asset, config=None):
    """Main entry point: extract and prepare preview for one asset."""
    if config is None:
        config = load_config()

    safe_name = asset.get('safe_name', asset.get('id', 'unknown'))
    filepath = asset.get('filepath', '')

    # Resolve relative paths to absolute
    if filepath and not os.path.isabs(filepath):
        filepath = os.path.join(ROOT_DIR, filepath)

    if not filepath or not os.path.exists(filepath):
        logger.error(f"Asset file not found: {filepath} (asset: {safe_name})")
        return None

    preview_dir = os.path.join(PREVIEW_BASE, safe_name)
    extract_dir = os.path.join(preview_dir, "extracted")
    textures_dir = os.path.join(preview_dir, "textures")
    models_dir = os.path.join(preview_dir, "models")

    # Clean previous
    if os.path.exists(preview_dir):
        shutil.rmtree(preview_dir, ignore_errors=True)

    for d in [preview_dir, textures_dir, models_dir]:
        os.makedirs(d, exist_ok=True)

    # Step 1: Extract archive
    logger.info(f"Extracting: {os.path.basename(filepath)}")
    if not extract_archive(filepath, extract_dir):
        return None

    # Step 1.5: Recursively extract nested archives (.zip, .rar, .7z inside the main archive)
    ARCHIVE_EXTS = {'.zip', '.rar', '.7z'}
    max_depth = 3  # prevent infinite recursion
    for depth in range(max_depth):
        nested_archives = []
        for root, _, fnames in os.walk(extract_dir):
            for fn in fnames:
                if os.path.splitext(fn)[1].lower() in ARCHIVE_EXTS:
                    nested_archives.append(os.path.join(root, fn))
        if not nested_archives:
            break
        logger.info(f"  Found {len(nested_archives)} nested archive(s) (depth {depth+1}), extracting...")
        for na in nested_archives:
            na_name = os.path.splitext(os.path.basename(na))[0]
            na_dir = os.path.join(os.path.dirname(na), f"_{na_name}")
            logger.info(f"    Extracting nested: {os.path.basename(na)}")
            if extract_archive(na, na_dir):
                try:
                    os.remove(na)  # remove the nested archive after successful extraction
                except OSError:
                    pass

    # Step 2: Categorize contents
    files = categorize_files(extract_dir)
    logger.info(f"  Found: {len(files['images'])} images, {len(files['models'])} 3D models, "
                f"{len(files['gta_files'])} GTA files, {len(files['rpf_files'])} RPF archives")

    # Step 3: Process loose textures and models
    converted_textures, converted_models = process_extracted_files(
        files, textures_dir, models_dir
    )

    # Step 4: Extract RPF archives (built-in parser, no CodeWalker needed)
    rpf_extracted = False
    if files['rpf_files'] and HAS_RPF_PARSER:
        rpf_extracted = _extract_rpf_textures(
            files['rpf_files'], textures_dir, models_dir,
            converted_textures, converted_models
        )
    elif files['rpf_files']:
        # Fallback: try CodeWalker if RPF parser not available
        for rpf in files['rpf_files']:
            rpf_out = os.path.join(extract_dir, f"_rpf_{os.path.splitext(rpf['name'])[0]}")
            if try_codewalker_extract(rpf['full_path'], rpf_out, config):
                rpf_extracted = True
                rpf_files_cat = categorize_files(rpf_out)
                extra_tex, extra_models = process_extracted_files(
                    rpf_files_cat, textures_dir, models_dir
                )
                for t in extra_tex:
                    t['from_rpf'] = True
                converted_textures.extend(extra_tex)
                converted_models.extend(extra_models)

    # Step 4.5: Process loose GTA files (.ytd textures, .yft models) outside RPFs
    if HAS_RPF_PARSER:
        _process_loose_gta_files(files['gta_files'], textures_dir, models_dir,
                                 converted_textures, converted_models)

    needs_cw = len(files['rpf_files']) > 0 and not rpf_extracted

    # Step 5: Preserve original dlc.rpf for repacking
    rpf_source = None
    for rpf in files['rpf_files']:
        if rpf['name'].lower() == 'dlc.rpf':
            original_dir = os.path.join(preview_dir, 'original')
            os.makedirs(original_dir, exist_ok=True)
            dest = os.path.join(original_dir, 'dlc.rpf')
            try:
                shutil.copy2(rpf['full_path'], dest)
                rpf_source = dest
                logger.info(f"  Preserved original dlc.rpf for repacking: {dest}")
            except Exception as e:
                logger.warning(f"  Failed to preserve dlc.rpf: {e}")
            break

    # Sort models: put the main model (most vertices) first
    converted_models.sort(key=lambda m: m.get('vertices', 0), reverse=True)

    # Build manifest
    manifest = {
        'asset_id': asset.get('id'),
        'safe_name': safe_name,
        'extracted_at': datetime.now().isoformat(),
        'archive_name': os.path.basename(filepath),
        'files': [{
            'path': f['path'], 'name': f['name'],
            'ext': f['ext'], 'size': f['size'],
            'size_display': f['size_display']
        } for f in files['all']],
        'textures': converted_textures,
        'models': converted_models,
        'gta_files': [{
            'path': f['path'], 'name': f['name'],
            'ext': f['ext'], 'size_display': f['size_display']
        } for f in files['gta_files']],
        'rpf_files': [{
            'path': f['path'], 'name': f['name'],
            'size_display': f['size_display']
        } for f in files['rpf_files']],
        'has_3d_preview': len(converted_models) > 0,
        'has_textures': len(converted_textures) > 0,
        'has_gta_files': len(files['gta_files']) > 0,
        'needs_codewalker': needs_cw,
        'rpf_extracted': rpf_extracted,
        'rpf_source': rpf_source
    }

    with open(os.path.join(preview_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Clean up extracted dir to save space (keep textures/models dirs)
    shutil.rmtree(extract_dir, ignore_errors=True)

    logger.info(f"  Preview ready: {len(converted_textures)} textures, "
                f"{len(converted_models)} 3D models")
    return manifest


def _extract_rpf_textures(rpf_entries, textures_dir, models_dir,
                          converted_textures, converted_models):
    """Extract textures from RPF archives using built-in parser."""
    any_extracted = False

    for rpf_info in rpf_entries:
        rpf_path = rpf_info['full_path']
        try:
            with open(rpf_path, 'rb') as f:
                rpf_data = f.read()

            rpf = RPFFile(rpf_data)
            _process_rpf_recursive(rpf, rpf_data, textures_dir, models_dir,
                                   converted_textures, converted_models, depth=0)
            any_extracted = True
        except Exception as e:
            logger.warning(f"  RPF parse failed for {rpf_info['name']}: {e}")

    return any_extracted


def _process_rpf_recursive(rpf, rpf_data, textures_dir, models_dir,
                           converted_textures, converted_models, depth=0):
    """Recursively process RPF entries, extracting textures from nested RPFs."""
    if depth > 5:
        return

    for entry in rpf.list_files():
        try:
            data = rpf.extract_file(entry)
            if data is None:
                continue

            # Nested RPF — recurse
            if entry.name.lower().endswith('.rpf') and len(data) >= 16:
                magic_check = struct.unpack_from('<I', data, 0)[0]
                if magic_check == 0x52504637:
                    nested = RPFFile(data)
                    _process_rpf_recursive(nested, data, textures_dir, models_dir,
                                          converted_textures, converted_models, depth + 1)
                continue

            # YTD texture dictionary
            if entry.name.lower().endswith('.ytd') and entry.is_resource:
                logger.info(f"  Extracting textures from {entry.name}")
                dds_dir = os.path.join(textures_dir, "_dds_temp")
                results = extract_textures_from_ytd(
                    data, entry.system_flags, entry.graphics_flags, dds_dir
                )
                # Convert extracted DDS to PNG
                for tex_info in results:
                    dds_path = tex_info['path']
                    png_name = os.path.splitext(tex_info['file'])[0] + '.png'
                    png_path = os.path.join(textures_dir, png_name)
                    if convert_texture_to_png(dds_path, png_path):
                        converted_textures.append({
                            'name': png_name,
                            'original': f"rpf:{entry.name}/{tex_info['name']}",
                            'original_name': tex_info['name'],
                            'preview': f"textures/{png_name}",
                            'format': tex_info['format'],
                            'width': tex_info['width'],
                            'height': tex_info['height'],
                            'from_rpf': True
                        })
                # Clean up DDS temp
                shutil.rmtree(dds_dir, ignore_errors=True)
                continue

            # YFT 3D model
            if entry.name.lower().endswith('.yft') and entry.is_resource:
                lower = entry.name.lower()
                if '_hi' in lower or '_lv' in lower or '_sc' in lower:
                    continue  # Skip LOD variants and scene containers
                logger.info(f"  Extracting 3D model from {entry.name}")
                glb_name = os.path.splitext(entry.name)[0] + '.glb'
                glb_path = os.path.join(models_dir, glb_name)
                result = extract_model_from_yft(
                    data, entry.system_flags, entry.graphics_flags, glb_path
                )
                if result:
                    converted_models.append({
                        'name': glb_name,
                        'original': f"rpf:{entry.name}",
                        'path': f"models/{glb_name}",
                        'preview': f"models/{glb_name}",
                        'format': 'GLB',
                        'meshes': result['meshes'],
                        'vertices': result['vertices'],
                        'triangles': result['triangles'],
                        'from_rpf': True
                    })
                continue

            # Loose meta/xml files from RPF — save for reference
            if entry.name.lower().endswith(('.meta', '.xml')):
                continue  # Already listed in file tree

        except Exception as e:
            logger.debug(f"  Error processing RPF entry {entry.name}: {e}")


def _decompress_rsc7(raw_data):
    """Decompress a loose RSC7 resource file.
    Returns (decompressed_data, sys_flags, gfx_flags) or (None, 0, 0) on failure.
    """
    if len(raw_data) < 16:
        return None, 0, 0

    magic = struct.unpack_from('<I', raw_data, 0)[0]
    is_rsc = (magic == 0x37435352 or  # RSC7
              (raw_data[0:2] == b'RS' and raw_data[3] == 0x37))
    if not is_rsc:
        return None, 0, 0

    sys_flags = struct.unpack_from('<I', raw_data, 8)[0]
    gfx_flags = struct.unpack_from('<I', raw_data, 12)[0]
    compressed = raw_data[16:]

    try:
        return zlib.decompress(compressed, -15), sys_flags, gfx_flags
    except zlib.error:
        try:
            return zlib.decompress(compressed), sys_flags, gfx_flags
        except zlib.error as e:
            logger.warning(f"  RSC7 decompression failed: {e}")
            return None, 0, 0


def _process_loose_gta_files(gta_files, textures_dir, models_dir,
                              converted_textures, converted_models):
    """Process loose .ytd and .yft files that aren't inside RPF archives."""
    for gta_file in gta_files:
        ext = gta_file['ext'].lower()
        try:
            with open(gta_file['full_path'], 'rb') as f:
                raw_data = f.read()

            if len(raw_data) < 16:
                continue

            # YTD texture dictionary (RSC7 resource)
            if ext == '.ytd':
                decompressed, sys_flags, gfx_flags = _decompress_rsc7(raw_data)
                if decompressed is None:
                    continue

                logger.info(f"  Extracting textures from loose {gta_file['name']} "
                            f"({len(raw_data)//1024}KB -> {len(decompressed)//1024}KB)")
                dds_dir = os.path.join(textures_dir, "_dds_temp")
                try:
                    results = extract_textures_from_ytd(
                        decompressed, sys_flags, gfx_flags, dds_dir
                    )
                    for tex_info in results:
                        dds_path = tex_info['path']
                        png_name = os.path.splitext(tex_info['file'])[0] + '.png'
                        png_path = os.path.join(textures_dir, png_name)
                        if convert_texture_to_png(dds_path, png_path):
                            converted_textures.append({
                                'name': png_name,
                                'original': f"ytd:{gta_file['name']}/{tex_info['name']}",
                                'original_name': tex_info['name'],
                                'preview': f"textures/{png_name}",
                                'format': tex_info['format'],
                                'width': tex_info['width'],
                                'height': tex_info['height'],
                                'from_ytd': True
                            })
                except Exception as e:
                    logger.warning(f"  Failed to extract {gta_file['name']}: {e}")
                finally:
                    shutil.rmtree(dds_dir, ignore_errors=True)

            # YFT 3D model (RSC7 resource)
            elif ext == '.yft':
                lower = gta_file['name'].lower()
                if '_hi' in lower or '_lv' in lower or '_sc' in lower:
                    continue

                decompressed, sys_flags, gfx_flags = _decompress_rsc7(raw_data)
                if decompressed is None:
                    continue

                logger.info(f"  Extracting 3D model from loose {gta_file['name']} "
                            f"({len(raw_data)//1024}KB -> {len(decompressed)//1024}KB)")
                glb_name = os.path.splitext(gta_file['name'])[0] + '.glb'
                glb_path = os.path.join(models_dir, glb_name)
                try:
                    result = extract_model_from_yft(decompressed, sys_flags, gfx_flags, glb_path)
                    if result:
                        converted_models.append({
                            'name': glb_name,
                            'original': f"yft:{gta_file['name']}",
                            'path': f"models/{glb_name}",
                            'preview': f"models/{glb_name}",
                            'format': 'GLB',
                            'meshes': result['meshes'],
                            'vertices': result['vertices'],
                            'triangles': result['triangles'],
                            'from_yft': True
                        })
                except Exception as e:
                    logger.warning(f"  Failed to extract {gta_file['name']}: {e}")

        except Exception as e:
            logger.debug(f"  Error processing loose GTA file {gta_file['name']}: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract asset previews")
    parser.add_argument("--asset-id", help="Specific asset ID or safe_name")
    parser.add_argument("--all", action="store_true", help="Process all assets")
    parser.add_argument("--force", action="store_true", help="Re-extract existing")
    args = parser.parse_args()

    config = load_config()
    index = load_index()

    targets = []
    if args.asset_id:
        for a in index['assets']:
            if a.get('id') == args.asset_id or a.get('safe_name') == args.asset_id:
                targets.append(a)
                break
        if not targets:
            logger.error(f"Asset not found: {args.asset_id}")
            return
    elif args.all:
        for a in index['assets']:
            sn = a.get('safe_name', '')
            manifest = os.path.join(PREVIEW_BASE, sn, "manifest.json")
            if args.force or not os.path.exists(manifest):
                targets.append(a)
    else:
        parser.print_help()
        return

    logger.info(f"Processing {len(targets)} asset(s)")
    os.makedirs(PREVIEW_BASE, exist_ok=True)

    results = []
    for asset in targets:
        result = extract_preview_for_asset(asset, config)
        if result:
            results.append(result)
            # Update index
            for idx_a in index['assets']:
                if idx_a.get('id') == asset.get('id'):
                    idx_a['has_preview'] = True
                    idx_a['preview_data'] = {
                        'has_3d': result['has_3d_preview'],
                        'has_textures': result['has_textures'],
                        'needs_codewalker': result['needs_codewalker'],
                        'texture_count': len(result['textures']),
                        'model_count': len(result['models']),
                        'file_count': len(result['files'])
                    }
                    break

    save_index(index)

    # Print JSON summary for Node.js integration
    print(json.dumps({
        'processed': len(results),
        'total': len(targets),
        'results': [{
            'safe_name': r['safe_name'],
            'textures': len(r['textures']),
            'models': len(r['models']),
            'has_3d': r['has_3d_preview']
        } for r in results]
    }))


if __name__ == "__main__":
    main()
