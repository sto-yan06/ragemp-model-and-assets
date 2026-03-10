"""
RPF7 archive parser for GTA V mod files.
Extracts files from Rockstar's RPF7 archive format (used in dlc.rpf and nested .rpf files).
"""
import struct
import zlib
import os
import logging

logger = logging.getLogger(__name__)

BLOCK_SIZE = 512
RPF7_MAGIC = 0x52504637  # "RPF7" in LE
RSC7_MAGIC = 0x37435352  # "RSC7" in LE
DIR_MARKER = 0x7FFFFF00


class RPFEntry:
    """Base class for RPF7 entries."""
    def __init__(self, name="", path=""):
        self.name = name
        self.path = path


class RPFDirectory(RPFEntry):
    """Directory entry in an RPF archive."""
    def __init__(self, name="", entries_index=0, entries_count=0):
        super().__init__(name)
        self.entries_index = entries_index
        self.entries_count = entries_count
        self.children = []


class RPFFileEntry(RPFEntry):
    """Binary file entry in an RPF archive."""
    def __init__(self, name="", offset=0, on_disk_size=0, uncompressed_size=0, is_resource=False):
        super().__init__(name)
        self.offset = offset
        self.on_disk_size = on_disk_size
        self.uncompressed_size = uncompressed_size
        self.is_resource = is_resource
        self.is_compressed = on_disk_size > 0
        self.system_flags = 0
        self.graphics_flags = 0


class RPFFile:
    """Parser for RPF7 archives."""

    def __init__(self, data):
        self.data = data
        self.entries = []
        self.root = None
        self._parse()

    def _parse(self):
        """Parse the RPF7 header, entries, and name table."""
        if len(self.data) < 16:
            raise ValueError("Data too small for RPF7 header")

        magic, entry_count, names_len, encryption = struct.unpack('<IIII', self.data[0:16])

        if magic != RPF7_MAGIC:
            raise ValueError(f"Not an RPF7 file (magic=0x{magic:08X})")

        enc_str = self.data[12:16].decode('ascii', errors='replace')
        if enc_str not in ('OPEN', 'NONE', '\x00\x00\x00\x00') and encryption != 0:
            raise ValueError(f"Encrypted RPF (enc={enc_str}) — cannot parse without keys")

        # Parse name table
        toc_start = 16
        names_start = toc_start + entry_count * 16
        names_data = self.data[names_start:names_start + names_len]
        names = {}
        i = 0
        while i < len(names_data):
            end = names_data.find(0, i)
            if end == -1:
                end = len(names_data)
            names[i] = names_data[i:end].decode('ascii', errors='replace')
            i = end + 1

        # Parse entries (16 bytes each)
        self.entries = []
        for e in range(entry_count):
            off = toc_start + e * 16
            raw = self.data[off:off + 16]
            v0, v1, v2, v3 = struct.unpack('<IIII', raw)

            if v1 == DIR_MARKER:
                entry = RPFDirectory(
                    name=names.get(v0 & 0xFFFF, ""),
                    entries_index=v2,
                    entries_count=v3,
                )
            else:
                # File entry — parse byte fields
                name_offset = raw[0] | (raw[1] << 8)
                on_disk_size = raw[2] | (raw[3] << 8) | (raw[4] << 16)
                is_resource = (raw[7] & 0x80) != 0

                if is_resource:
                    # Resource entries: 16-bit offset, byte[7]=0x80
                    offset_blocks = raw[5] | (raw[6] << 8)
                else:
                    # Binary entries: 24-bit offset
                    offset_blocks = raw[5] | (raw[6] << 8) | (raw[7] << 16)

                entry = RPFFileEntry(
                    name=names.get(name_offset, ""),
                    offset=offset_blocks * BLOCK_SIZE,
                    on_disk_size=on_disk_size,
                    uncompressed_size=v2,
                    is_resource=is_resource,
                )
                if is_resource:
                    entry.system_flags = v2
                    entry.graphics_flags = v3

            self.entries.append(entry)

        # Build directory tree
        if self.entries:
            self.root = self.entries[0] if isinstance(self.entries[0], RPFDirectory) else None
            if self.root:
                self._build_tree(self.root, "")

    def _build_tree(self, directory, parent_path):
        """Recursively build directory tree."""
        path = f"{parent_path}/{directory.name}" if directory.name else ""
        directory.path = path

        start = directory.entries_index
        count = directory.entries_count

        for i in range(start, min(start + count, len(self.entries))):
            child = self.entries[i]
            child.path = f"{path}/{child.name}" if path else child.name

            if isinstance(child, RPFDirectory):
                self._build_tree(child, path)

            directory.children.append(child)

    def extract_file(self, entry):
        """Extract a single file entry's data."""
        if isinstance(entry, RPFDirectory):
            return None

        if entry.is_resource:
            return self._extract_resource(entry)
        else:
            return self._extract_binary(entry)

    def _extract_binary(self, entry):
        """Extract a binary (non-resource) file."""
        offset = entry.offset
        if entry.is_compressed and entry.on_disk_size > 0:
            compressed = self.data[offset:offset + entry.on_disk_size]
            try:
                return zlib.decompress(compressed, -15)
            except zlib.error:
                try:
                    return zlib.decompress(compressed)
                except zlib.error as e:
                    logger.warning(f"Failed to decompress {entry.name}: {e}")
                    return compressed
        else:
            size = entry.uncompressed_size
            return self.data[offset:offset + size]

    def _extract_resource(self, entry):
        """Extract a resource file (RSC7) — returns raw decompressed data."""
        offset = entry.offset
        on_disk = entry.on_disk_size if entry.on_disk_size > 0 else 0

        # Read RSC7 header (accept variant RSC headers: "RS" + any byte + "7")
        rsc_header = self.data[offset:offset + 16]
        if len(rsc_header) < 16:
            return None

        rsc_magic = struct.unpack_from('<I', rsc_header, 0)[0]
        is_rsc = (rsc_magic == RSC7_MAGIC or
                  (rsc_header[0:2] == b'RS' and rsc_header[3] == 0x37))

        if not is_rsc:
            logger.warning(f"No RSC7 header for {entry.name} (magic=0x{rsc_magic:08X})")
            # Try extracting raw data
            if on_disk > 0:
                return self.data[offset:offset + on_disk]
            return None

        rsc_version = struct.unpack_from('<I', rsc_header, 4)[0]

        # Determine actual compressed data size
        # on_disk_size=0xFFFFFF means overflow (>16MB) — read until decompression succeeds
        if on_disk > 16 and on_disk != 0xFFFFFF:
            compressed = self.data[offset + 16:offset + on_disk]
        else:
            end = min(offset + 100_000_000, len(self.data))
            compressed = self.data[offset + 16:end]

        try:
            decompressed = zlib.decompress(compressed, -15)
            return decompressed
        except zlib.error:
            try:
                decompressed = zlib.decompress(compressed)
                return decompressed
            except zlib.error as e:
                logger.warning(f"Failed to decompress resource {entry.name}: {e}")
                return None

    def list_files(self):
        """Return a flat list of all file entries with their paths."""
        result = []
        for entry in self.entries:
            if isinstance(entry, RPFFileEntry):
                result.append(entry)
        return result

    def find_files(self, extension):
        """Find all files with a given extension."""
        ext = extension.lower()
        return [e for e in self.list_files() if e.name.lower().endswith(ext)]

    def walk(self, directory=None):
        """Walk the directory tree, yielding (path, dirs, files) tuples."""
        if directory is None:
            directory = self.root
        if directory is None:
            return

        dirs = [c for c in directory.children if isinstance(c, RPFDirectory)]
        files = [c for c in directory.children if isinstance(c, RPFFileEntry)]
        yield (directory.path, dirs, files)

        for d in dirs:
            yield from self.walk(d)

    def print_tree(self, directory=None, depth=0):
        """Print the directory tree."""
        if directory is None:
            directory = self.root
        if directory is None:
            return

        prefix = "  " * depth
        print(f"{prefix}[{directory.name or '/'}]")
        for child in directory.children:
            if isinstance(child, RPFDirectory):
                self.print_tree(child, depth + 1)
            else:
                size_str = f"{child.uncompressed_size:,}" if not child.is_resource else f"RSC7"
                comp = " (compressed)" if child.is_compressed else ""
                print(f"{prefix}  {child.name} [{size_str}{comp}]")


def find_entry_by_name(rpf, name, search_path=None):
    """Find a file entry by name (or partial path) in the RPF.
    
    Args:
        rpf: RPFFile instance
        name: Filename to search for (e.g. 'handling.meta')
        search_path: Optional path filter (e.g. 'common/data')
    Returns:
        RPFFileEntry or None
    """
    name_lower = name.lower()
    candidates = []
    for entry in rpf.list_files():
        if entry.name.lower() == name_lower:
            if search_path:
                if search_path.lower() in entry.path.lower():
                    candidates.append(entry)
            else:
                candidates.append(entry)
    
    if not candidates:
        return None
    # Prefer entries deeper in common/data path
    for c in candidates:
        if 'common/data' in c.path.lower():
            return c
    return candidates[0]


def replace_file_in_rpf(rpf_path, target_filename, new_data, output_path=None):
    """Replace a file inside an RPF7 archive.
    
    Strategy:
    1. Parse the RPF to find the target entry
    2. Compress the new data
    3. If compressed data fits in old space → write in-place
    4. Otherwise → append at end, update TOC offset
    5. Update TOC entry (on_disk_size, offset, uncompressed_size)
    
    Args:
        rpf_path: Path to the RPF file
        target_filename: Name of the file to replace (e.g. 'handling.meta')
        new_data: New file content (bytes)
        output_path: Output path (None = overwrite in place)
    Returns:
        True on success, raises on failure
    """
    with open(rpf_path, 'rb') as f:
        rpf_data = bytearray(f.read())
    
    rpf = RPFFile(bytes(rpf_data))
    
    entry = find_entry_by_name(rpf, target_filename)
    if entry is None:
        raise FileNotFoundError(f"'{target_filename}' not found in RPF archive")
    
    if entry.is_resource:
        raise ValueError(f"Cannot replace resource files (RSC7): {target_filename}")
    
    # Compress new data with raw deflate (wbits=-15: no zlib header, matching RPF format)
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed_new = compressor.compress(new_data) + compressor.flush()
    
    logger.info(f"RPF replace: {target_filename}")
    logger.info(f"  Original: offset=0x{entry.offset:X}, on_disk={entry.on_disk_size}, uncompressed={entry.uncompressed_size}")
    logger.info(f"  New: compressed={len(compressed_new)}, uncompressed={len(new_data)}")
    
    # Find the entry index to update TOC
    entry_idx = None
    for i, e in enumerate(rpf.entries):
        if e is entry:
            entry_idx = i
            break
    
    if entry_idx is None:
        raise RuntimeError("Could not find entry in TOC")
    
    # Read header to get toc_start
    magic, entry_count, names_len, encryption = struct.unpack('<IIII', rpf_data[0:16])
    toc_start = 16
    toc_offset = toc_start + entry_idx * 16
    
    # Determine write strategy
    old_disk_size = entry.on_disk_size
    new_disk_size = len(compressed_new)
    
    if new_disk_size <= old_disk_size and entry.offset > 0:
        # Fits in place — write at same offset
        write_offset = entry.offset
        # Zero out old data first
        rpf_data[write_offset:write_offset + old_disk_size] = b'\x00' * old_disk_size
        rpf_data[write_offset:write_offset + new_disk_size] = compressed_new
        new_offset_blocks = entry.offset // BLOCK_SIZE
        logger.info(f"  Strategy: in-place at 0x{write_offset:X}")
    else:
        # Append at end, block-aligned
        current_len = len(rpf_data)
        # Align to next block boundary
        aligned = ((current_len + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
        padding = aligned - current_len
        rpf_data.extend(b'\x00' * padding)
        write_offset = len(rpf_data)
        rpf_data.extend(compressed_new)
        # Pad to block boundary
        remainder = len(compressed_new) % BLOCK_SIZE
        if remainder:
            rpf_data.extend(b'\x00' * (BLOCK_SIZE - remainder))
        new_offset_blocks = write_offset // BLOCK_SIZE
        logger.info(f"  Strategy: append at 0x{write_offset:X} (block {new_offset_blocks})")
    
    # Update TOC entry
    # Binary file entry format (16 bytes):
    # [0:2] name_offset (16-bit) — keep original
    # [2:5] on_disk_size (24-bit LE)
    # [5:8] offset_blocks (24-bit LE, top bit of byte[7] = is_resource=0)
    # [8:12] uncompressed_size (32-bit LE)
    # [12:16] unused for binary (keep as-is)
    
    old_toc = bytearray(rpf_data[toc_offset:toc_offset + 16])
    
    # Keep name_offset (bytes 0-1)
    # Set on_disk_size (bytes 2-4, 24-bit LE)
    old_toc[2] = new_disk_size & 0xFF
    old_toc[3] = (new_disk_size >> 8) & 0xFF
    old_toc[4] = (new_disk_size >> 16) & 0xFF
    
    # Set offset_blocks (bytes 5-7, 24-bit LE, clear resource bit)
    old_toc[5] = new_offset_blocks & 0xFF
    old_toc[6] = (new_offset_blocks >> 8) & 0xFF
    old_toc[7] = (new_offset_blocks >> 16) & 0x7F  # Clear bit 7 (not resource)
    
    # Set uncompressed_size (bytes 8-11)
    uncompressed = len(new_data)
    old_toc[8] = uncompressed & 0xFF
    old_toc[9] = (uncompressed >> 8) & 0xFF
    old_toc[10] = (uncompressed >> 16) & 0xFF
    old_toc[11] = (uncompressed >> 24) & 0xFF
    
    rpf_data[toc_offset:toc_offset + 16] = old_toc
    
    # Write output
    out = output_path or rpf_path
    with open(out, 'wb') as f:
        f.write(rpf_data)
    
    logger.info(f"  Written to: {out} ({len(rpf_data):,} bytes)")
    return True


def get_rsc_sizes(sys_flags, gfx_flags):
    """Compute system and graphics virtual sizes from RSC7 flags."""
    def calc_size(flags):
        base = 0x2000 << (flags & 0xF)
        p0 = (flags >> 17) & 0x7F  # pages at base size
        p1 = (flags >> 11) & 0x3F  # pages at base/2
        p2 = (flags >> 7) & 0xF    # pages at base/4
        p3 = (flags >> 5) & 0x3    # pages at base/8
        p4 = (flags >> 4) & 0x1    # pages at base/16
        total = base * p0
        total += (base >> 1) * p1
        total += (base >> 2) * p2
        total += (base >> 3) * p3
        total += (base >> 4) * p4
        return max(total, base)  # At least one base page

    return calc_size(sys_flags), calc_size(gfx_flags)


def extract_rpf_from_archive(archive_path, target_dir):
    """Extract all RPF contents from a zip/7z archive to target_dir.
    
    Returns list of (file_path, file_info_dict) tuples for extracted files.
    """
    import tempfile

    ext = os.path.splitext(archive_path)[1].lower()
    extracted = []

    # First extract the archive to find RPF files
    with tempfile.TemporaryDirectory() as tmpdir:
        rpf_files = []

        if ext == '.zip':
            import zipfile
            with zipfile.ZipFile(archive_path) as z:
                for name in z.namelist():
                    if name.lower().endswith('.rpf'):
                        with z.open(name) as f:
                            rpf_data = f.read()
                        rpf_files.append((name, rpf_data))
        elif ext == '.7z':
            import py7zr
            with py7zr.SevenZipFile(archive_path) as z:
                all_names = z.getnames()
                rpf_names = [n for n in all_names if n.lower().endswith('.rpf')]
                if rpf_names:
                    z.extract(targets=rpf_names, path=tmpdir)
                    for rn in rpf_names:
                        fp = os.path.join(tmpdir, rn)
                        if os.path.exists(fp):
                            with open(fp, 'rb') as f:
                                rpf_data = f.read()
                            rpf_files.append((rn, rpf_data))

        # Parse each RPF
        for rpf_name, rpf_data in rpf_files:
            try:
                rpf = RPFFile(rpf_data)
                extracted.extend(
                    _extract_rpf_recursive(rpf, rpf_data, target_dir, rpf_name)
                )
            except Exception as e:
                logger.error(f"Failed to parse RPF {rpf_name}: {e}")

    return extracted


def _extract_rpf_recursive(rpf, rpf_data, target_dir, rpf_name, depth=0):
    """Recursively extract files from RPF, including nested RPFs."""
    if depth > 5:
        return []

    extracted = []

    for entry in rpf.list_files():
        try:
            data = rpf.extract_file(entry)
            if data is None:
                continue

            # Check if this is a nested RPF
            if entry.name.lower().endswith('.rpf') and len(data) > 16:
                magic_check = struct.unpack_from('<I', data, 0)[0]
                if magic_check == RPF7_MAGIC:
                    nested_rpf = RPFFile(data)
                    nested_name = f"{rpf_name}/{entry.name}"
                    extracted.extend(
                        _extract_rpf_recursive(nested_rpf, data, target_dir, nested_name, depth + 1)
                    )
                    continue

            # Save the file
            rel_path = entry.path.lstrip('/')
            out_path = os.path.join(target_dir, rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            with open(out_path, 'wb') as f:
                f.write(data)

            info = {
                'name': entry.name,
                'path': rel_path,
                'size': len(data),
                'is_resource': entry.is_resource,
                'ext': os.path.splitext(entry.name)[1].lower(),
            }
            if entry.is_resource:
                info['system_flags'] = entry.system_flags
                info['graphics_flags'] = entry.graphics_flags

            extracted.append((out_path, info))
            logger.info(f"  Extracted: {rel_path} ({len(data):,} bytes)")

        except Exception as e:
            logger.warning(f"  Failed to extract {entry.name}: {e}")

    return extracted
