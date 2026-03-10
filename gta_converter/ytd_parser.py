"""
YTD texture dictionary parser for GTA V.
Extracts DDS textures from decompressed RSC7 .ytd resource data.
"""
import struct
import os
import logging

logger = logging.getLogger(__name__)

# D3DFORMAT constants
D3DFMT_A8R8G8B8 = 21
D3DFMT_X8R8G8B8 = 22
D3DFMT_A1R5G5B5 = 25
D3DFMT_R5G6B5 = 23
D3DFMT_A8 = 28
D3DFMT_L8 = 50
D3DFMT_DXT1 = 0x31545844  # "DXT1" as FourCC
D3DFMT_DXT3 = 0x33545844  # "DXT3"
D3DFMT_DXT5 = 0x35545844  # "DXT5"
D3DFMT_ATI1 = 0x31495441  # "ATI1" (BC4)
D3DFMT_ATI2 = 0x32495441  # "ATI2" (BC5)

# Bytes per pixel / block info
FORMAT_INFO = {
    D3DFMT_A8R8G8B8: {'bpp': 4, 'block': False, 'name': 'A8R8G8B8'},
    D3DFMT_X8R8G8B8: {'bpp': 4, 'block': False, 'name': 'X8R8G8B8'},
    D3DFMT_A1R5G5B5: {'bpp': 2, 'block': False, 'name': 'A1R5G5B5'},
    D3DFMT_R5G6B5:   {'bpp': 2, 'block': False, 'name': 'R5G6B5'},
    D3DFMT_A8:        {'bpp': 1, 'block': False, 'name': 'A8'},
    D3DFMT_L8:        {'bpp': 1, 'block': False, 'name': 'L8'},
    D3DFMT_DXT1:      {'bpp': 0, 'block': True, 'block_size': 8,  'name': 'DXT1'},
    D3DFMT_DXT3:      {'bpp': 0, 'block': True, 'block_size': 16, 'name': 'DXT3'},
    D3DFMT_DXT5:      {'bpp': 0, 'block': True, 'block_size': 16, 'name': 'DXT5'},
    D3DFMT_ATI1:      {'bpp': 0, 'block': True, 'block_size': 8,  'name': 'ATI1/BC4'},
    D3DFMT_ATI2:      {'bpp': 0, 'block': True, 'block_size': 16, 'name': 'ATI2/BC5'},
}

# Texture struct field offsets (within a grcTexturePC structure)
TEX_NAME_PTR = 0x28    # uint64: pointer to name string
TEX_WIDTH = 0x50       # uint16
TEX_HEIGHT = 0x52      # uint16
TEX_DEPTH = 0x54       # uint16
TEX_STRIDE = 0x56      # uint16
TEX_FORMAT = 0x58      # uint32: D3DFORMAT or FourCC
TEX_MIPS = 0x5D        # uint8: mip level count
TEX_DATA_PTR = 0x70    # uint64: pointer to pixel data (graphics section)
TEX_STRUCT_SIZE = 0x90 # 144 bytes per texture structure


def get_system_size(sys_flags):
    """Compute system data virtual size from RSC7 system flags."""
    base = 0x2000 << (sys_flags & 0xF)
    p0 = (sys_flags >> 17) & 0x7F
    p1 = (sys_flags >> 11) & 0x3F
    p2 = (sys_flags >> 7) & 0xF
    p3 = (sys_flags >> 5) & 0x3
    p4 = (sys_flags >> 4) & 0x1
    total = base * p0
    total += (base >> 1) * p1
    total += (base >> 2) * p2
    total += (base >> 3) * p3
    total += (base >> 4) * p4
    return max(total, base)


def compute_mip_data_size(width, height, format_code, mip_levels):
    """Compute the total byte size of all mip levels for a texture."""
    info = FORMAT_INFO.get(format_code)
    if not info:
        return 0

    total = 0
    w, h = width, height

    for _ in range(mip_levels):
        if info['block']:
            bw = max(1, (w + 3) // 4)
            bh = max(1, (h + 3) // 4)
            total += bw * bh * info['block_size']
        else:
            total += w * h * info['bpp']

        w = max(1, w >> 1)
        h = max(1, h >> 1)

    return total


def make_dds_header(width, height, mip_count, format_code):
    """Create a DDS file header (128 bytes)."""
    # Flags
    DDSD_CAPS = 0x1
    DDSD_HEIGHT = 0x2
    DDSD_WIDTH = 0x4
    DDSD_PIXELFORMAT = 0x1000
    DDSD_MIPMAPCOUNT = 0x20000
    DDSD_LINEARSIZE = 0x80000
    DDSD_PITCH = 0x8

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if mip_count > 1:
        flags |= DDSD_MIPMAPCOUNT

    info = FORMAT_INFO.get(format_code, {})
    is_block = info.get('block', False)

    if is_block:
        flags |= DDSD_LINEARSIZE
        bs = info['block_size']
        pitch_or_linear = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * bs
    else:
        flags |= DDSD_PITCH
        bpp = info.get('bpp', 4)
        pitch_or_linear = width * bpp

    # DDSURFACEDESC2 struct
    header = b'DDS '  # magic
    header += struct.pack('<I', 124)        # struct size
    header += struct.pack('<I', flags)
    header += struct.pack('<I', height)
    header += struct.pack('<I', width)
    header += struct.pack('<I', pitch_or_linear)
    header += struct.pack('<I', 0)           # depth
    header += struct.pack('<I', mip_count)
    header += b'\x00' * 44                  # reserved1[11]

    # DDPIXELFORMAT (32 bytes)
    pf_size = 32
    if is_block:
        pf_flags = 0x4  # DDPF_FOURCC
        pf = struct.pack('<II', pf_size, pf_flags)
        pf += struct.pack('<I', format_code)  # FourCC
        pf += struct.pack('<IIIII', 0, 0, 0, 0, 0)  # bits, masks
    elif format_code in (D3DFMT_A8R8G8B8, D3DFMT_X8R8G8B8):
        has_alpha = format_code == D3DFMT_A8R8G8B8
        pf_flags = 0x40 | (0x1 if has_alpha else 0)  # DDPF_RGB | DDPF_ALPHAPIXELS
        pf = struct.pack('<II', pf_size, pf_flags)
        pf += struct.pack('<I', 0)           # FourCC = 0
        pf += struct.pack('<I', 32)          # RGB bit count
        pf += struct.pack('<I', 0x00FF0000)  # R mask
        pf += struct.pack('<I', 0x0000FF00)  # G mask
        pf += struct.pack('<I', 0x000000FF)  # B mask
        pf += struct.pack('<I', 0xFF000000 if has_alpha else 0)  # A mask
    elif format_code in (D3DFMT_A8, D3DFMT_L8):
        pf_flags = 0x20000  # DDPF_LUMINANCE (for single channel)
        pf = struct.pack('<II', pf_size, pf_flags)
        pf += struct.pack('<I', 0)           # FourCC
        pf += struct.pack('<I', 8)           # bit count
        pf += struct.pack('<I', 0xFF)        # mask
        pf += struct.pack('<III', 0, 0, 0)   # other masks
    else:
        # Fallback: treat as A8R8G8B8
        pf = struct.pack('<II', pf_size, 0x41)
        pf += struct.pack('<I', 0)
        pf += struct.pack('<I', 32)
        pf += struct.pack('<IIII', 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)

    header += pf

    # DDSCAPS (16 bytes)
    caps1 = 0x1000  # DDSCAPS_TEXTURE
    if mip_count > 1:
        caps1 |= 0x400008  # DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    header += struct.pack('<I', caps1)
    header += struct.pack('<III', 0, 0, 0)  # caps2, caps3, caps4

    header += struct.pack('<I', 0)  # reserved2

    return header


class TextureInfo:
    """Info about a single texture in a YTD."""
    def __init__(self):
        self.name = ""
        self.width = 0
        self.height = 0
        self.depth = 1
        self.stride = 0
        self.format = 0
        self.format_name = ""
        self.mip_levels = 1
        self.data_offset = 0  # offset in decompressed data
        self.data_size = 0


def parse_ytd(decompressed_data, sys_flags, gfx_flags):
    """Parse a decompressed YTD texture dictionary.
    
    Args:
        decompressed_data: Raw decompressed RSC7 data
        sys_flags: System flags from RPF entry or RSC7 header
        gfx_flags: Graphics flags from RPF entry or RSC7 header
    
    Returns:
        List of TextureInfo objects
    """
    data = decompressed_data
    sys_size = get_system_size(sys_flags)

    if len(data) < 0x40:
        return []

    # TextureDictionary structure:
    # +0x00: vftable (8 bytes)
    # +0x08: pointer (8 bytes)
    # +0x20: hash collection pointer (8 bytes)
    # +0x28: hash collection count (4+4 bytes: capacity, count)
    # +0x30: texture collection pointer (8 bytes)
    # +0x38: texture collection count (4+4 bytes: capacity, count)

    count_lo = struct.unpack_from('<H', data, 0x28)[0]
    count_hi = struct.unpack_from('<H', data, 0x2A)[0]
    tex_count = min(count_lo, count_hi)  # Both should match
    if tex_count == 0 or tex_count > 1000:
        # Try alternative: the values might be at different offsets
        # Scan for a reasonable count
        logger.warning(f"Unusual texture count {count_lo}/{count_hi}, trying scan")
        tex_count = 0

    tex_array_ptr = struct.unpack_from('<Q', data, 0x30)[0]

    if tex_array_ptr < 0x50000000 or tex_array_ptr > 0x50FFFFFF:
        # Try offset 0x20 for the texture array pointer
        tex_array_ptr = struct.unpack_from('<Q', data, 0x20)[0]
        if tex_array_ptr < 0x50000000 or tex_array_ptr > 0x50FFFFFF:
            logger.warning("Cannot find texture array pointer")
            return []

    # Resolve texture array pointer
    tex_array_off = tex_array_ptr - 0x50000000
    if tex_array_off + tex_count * 8 > len(data):
        logger.warning("Texture array extends beyond data")
        return []

    textures = []

    for i in range(tex_count):
        try:
            # Read texture struct pointer
            tex_ptr = struct.unpack_from('<Q', data, tex_array_off + i * 8)[0]
            if tex_ptr < 0x50000000 or tex_ptr > 0x50FFFFFF:
                continue
            tex_off = tex_ptr - 0x50000000

            if tex_off + TEX_STRUCT_SIZE > len(data):
                continue

            tex = TextureInfo()

            # Read name
            name_ptr = struct.unpack_from('<Q', data, tex_off + TEX_NAME_PTR)[0]
            if 0x50000000 <= name_ptr <= 0x50FFFFFF:
                name_off = name_ptr - 0x50000000
                end = data.find(0, name_off, name_off + 256)
                if end > name_off:
                    tex.name = data[name_off:end].decode('ascii', errors='replace')

            # Read dimensions
            tex.width = struct.unpack_from('<H', data, tex_off + TEX_WIDTH)[0]
            tex.height = struct.unpack_from('<H', data, tex_off + TEX_HEIGHT)[0]
            tex.depth = struct.unpack_from('<H', data, tex_off + TEX_DEPTH)[0]
            tex.stride = struct.unpack_from('<H', data, tex_off + TEX_STRIDE)[0]

            # Read format
            tex.format = struct.unpack_from('<I', data, tex_off + TEX_FORMAT)[0]
            info = FORMAT_INFO.get(tex.format)
            tex.format_name = info['name'] if info else f"0x{tex.format:X}"

            # Read mip levels
            tex.mip_levels = data[tex_off + TEX_MIPS]
            if tex.mip_levels == 0:
                # Try adjacent byte
                tex.mip_levels = data[tex_off + TEX_MIPS - 1]
            if tex.mip_levels == 0:
                tex.mip_levels = 1

            # Read data pointer
            data_ptr = struct.unpack_from('<Q', data, tex_off + TEX_DATA_PTR)[0]
            if data_ptr >= 0x60000000:
                gfx_offset = data_ptr - 0x60000000
                tex.data_offset = sys_size + gfx_offset
            elif data_ptr >= 0x50000000:
                tex.data_offset = data_ptr - 0x50000000

            # Compute data size
            tex.data_size = compute_mip_data_size(
                tex.width, tex.height, tex.format, tex.mip_levels
            )

            # Validate
            if tex.width > 0 and tex.height > 0 and tex.width <= 16384 and tex.height <= 16384:
                textures.append(tex)
                logger.debug(
                    f"  Texture: {tex.name} {tex.width}x{tex.height} "
                    f"{tex.format_name} mips={tex.mip_levels} "
                    f"data_off=0x{tex.data_offset:X} size={tex.data_size:,}"
                )

        except Exception as e:
            logger.debug(f"  Error parsing texture {i}: {e}")
            continue

    return textures


def extract_textures_from_ytd(decompressed_data, sys_flags, gfx_flags, output_dir):
    """Extract all textures from a decompressed YTD to DDS files.
    
    Args:
        decompressed_data: Raw decompressed RSC7 data
        sys_flags: System flags
        gfx_flags: Graphics flags
        output_dir: Directory to write DDS files
    
    Returns:
        List of dicts with extracted texture info
    """
    textures = parse_ytd(decompressed_data, sys_flags, gfx_flags)
    if not textures:
        return []

    os.makedirs(output_dir, exist_ok=True)
    results = []

    for tex in textures:
        try:
            if tex.data_offset <= 0 or tex.data_size <= 0:
                logger.warning(f"  Skipping {tex.name}: no data (off=0x{tex.data_offset:X}, size={tex.data_size})")
                continue

            if tex.data_offset + tex.data_size > len(decompressed_data):
                logger.warning(f"  Skipping {tex.name}: data beyond file bounds")
                continue

            # Read pixel data
            pixel_data = decompressed_data[tex.data_offset:tex.data_offset + tex.data_size]

            # Create DDS header
            dds_header = make_dds_header(tex.width, tex.height, tex.mip_levels, tex.format)

            # Write DDS file
            safe_name = tex.name.replace('/', '_').replace('\\', '_')
            if not safe_name.lower().endswith('.dds'):
                safe_name += '.dds'
            dds_path = os.path.join(output_dir, safe_name)

            with open(dds_path, 'wb') as f:
                f.write(dds_header)
                f.write(pixel_data)

            results.append({
                'name': tex.name,
                'file': safe_name,
                'path': dds_path,
                'width': tex.width,
                'height': tex.height,
                'format': tex.format_name,
                'mip_levels': tex.mip_levels,
                'data_size': tex.data_size,
            })

            logger.info(f"  Texture: {tex.name} {tex.width}x{tex.height} {tex.format_name} -> {safe_name}")

        except Exception as e:
            logger.warning(f"  Failed to extract texture {tex.name}: {e}")

    return results
