"""
YFT (Fragment Type) 3D model parser for GTA V.
Extracts geometry from decompressed RSC7 .yft resource data and converts to GLB.

Structure chain: fragType -> Drawable -> ModelCollection -> Model -> Geometry
                 -> VertexBuffer / IndexBuffer
"""
import struct
import os
import json
import logging
import numpy as np

logger = logging.getLogger(__name__)


def _resolve(ptr):
    """Resolve a system virtual pointer to an offset."""
    if 0x50000000 <= ptr <= 0x5FFFFFFF:
        return ptr - 0x50000000
    return None


def _read_ptr(data, off):
    """Read a uint64 pointer and resolve it."""
    if off + 8 > len(data):
        return None
    ptr = struct.unpack_from('<Q', data, off)[0]
    return _resolve(ptr)


def _read_u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def _read_u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


class MeshData:
    """Extracted mesh geometry."""
    def __init__(self):
        self.positions = None   # float32 array (N, 3)
        self.normals = None     # float32 array (N, 3)
        self.uvs = None         # float32 array (N, 2)
        self.indices = None     # uint32 array (M,)
        self.shader_index = 0


def parse_yft(data, sys_flags, gfx_flags):
    """Parse a decompressed YFT and return a list of MeshData objects.

    Args:
        data: Raw decompressed RSC7 data
        sys_flags: System flags from RPF entry
        gfx_flags: Graphics flags from RPF entry

    Returns:
        List of MeshData objects
    """
    if len(data) < 0x40:
        return []

    # fragType root at offset 0 — drawable pointer at +0x30
    drawable_off = _read_ptr(data, 0x30)
    if drawable_off is None:
        # Try alternate offset +0x28
        drawable_off = _read_ptr(data, 0x28)
    if drawable_off is None:
        logger.warning("Cannot find Drawable pointer in fragType")
        return []

    logger.debug(f"  Drawable at 0x{drawable_off:X}")
    return _parse_drawable(data, drawable_off)


def _parse_drawable(data, draw_off):
    """Parse a gtaDrawable structure."""
    meshes = []

    # ModelCollection pointer at Drawable+0x50
    # Try multiple LODs at +0x50, +0x58, +0x60, +0x68 (high/med/low/vlow)
    for lod_off in (0x50,):  # Only use high-detail LOD
        mc_off = _read_ptr(data, draw_off + lod_off)
        if mc_off is None:
            continue

        # ModelCollection: +0x00 = model array ptr, +0x08 = count(u16)
        model_arr_off = _read_ptr(data, mc_off)
        if model_arr_off is None:
            continue
        model_count = _read_u16(data, mc_off + 0x08)

        if model_count == 0 or model_count > 100:
            continue

        logger.debug(f"  ModelCollection at 0x{mc_off:X}: {model_count} model(s)")

        for mi in range(model_count):
            model_ptr_off = model_arr_off + mi * 8
            model_off = _read_ptr(data, model_ptr_off)
            if model_off is None:
                continue

            model_meshes = _parse_model(data, model_off)
            meshes.extend(model_meshes)

    return meshes


def _parse_model(data, model_off):
    """Parse a grmModel structure."""
    meshes = []

    # Geometry array pointer at +0x08, count at +0x10
    geom_arr_off = _read_ptr(data, model_off + 0x08)
    if geom_arr_off is None:
        return meshes

    geom_count = _read_u16(data, model_off + 0x10)
    if geom_count == 0 or geom_count > 500:
        return meshes

    # Shader mapping at +0x20
    shader_map_off = _read_ptr(data, model_off + 0x20)

    logger.debug(f"  Model at 0x{model_off:X}: {geom_count} geometries")

    for gi in range(geom_count):
        geom_off = _read_ptr(data, geom_arr_off + gi * 8)
        if geom_off is None:
            continue

        shader_idx = 0
        if shader_map_off is not None and shader_map_off + (gi + 1) * 2 <= len(data):
            shader_idx = _read_u16(data, shader_map_off + gi * 2)

        mesh = _parse_geometry(data, geom_off)
        if mesh is not None:
            mesh.shader_index = shader_idx
            meshes.append(mesh)

    return meshes


def _parse_geometry(data, geom_off):
    """Parse a grmGeometry structure and extract vertex/index data."""
    # VertexBuffer at +0x18
    vbuf_off = _read_ptr(data, geom_off + 0x18)
    # IndexBuffer at +0x38
    ibuf_off = _read_ptr(data, geom_off + 0x38)

    if vbuf_off is None or ibuf_off is None:
        return None

    # Index count at Geometry+0x58
    index_count = _read_u32(data, geom_off + 0x58)

    # VertexBuffer: stride at +0x08, data_ptr at +0x10, vertex_count at +0x18
    stride = _read_u32(data, vbuf_off + 0x08)
    vdata_off = _read_ptr(data, vbuf_off + 0x10)
    vertex_count = _read_u32(data, vbuf_off + 0x18)

    # IndexBuffer: index_count at +0x08, data_ptr at +0x10
    ib_count = _read_u32(data, ibuf_off + 0x08)
    idata_off = _read_ptr(data, ibuf_off + 0x10)

    if vdata_off is None or idata_off is None:
        return None
    if vertex_count == 0 or ib_count == 0:
        return None
    if stride < 44 or stride > 128:
        return None

    # Use the geometry-level index count if available, fall back to ibuf count
    if index_count == 0:
        index_count = ib_count

    # Validate bounds
    vdata_end = vdata_off + vertex_count * stride
    idata_end = idata_off + index_count * 2
    if vdata_end > len(data) or idata_end > len(data):
        logger.debug(f"  Geometry data out of bounds: verts={vertex_count} stride={stride}")
        return None

    mesh = MeshData()

    # Extract vertices: Position float3@+0, Normal float3@+20, UV float2@+36
    positions = np.zeros((vertex_count, 3), dtype=np.float32)
    normals = np.zeros((vertex_count, 3), dtype=np.float32)
    uvs = np.zeros((vertex_count, 2), dtype=np.float32)

    for vi in range(vertex_count):
        base = vdata_off + vi * stride

        # Position (float3 at +0)
        positions[vi] = struct.unpack_from('<3f', data, base)

        # Normal (float3 at +20)
        normals[vi] = struct.unpack_from('<3f', data, base + 20)

        # UV (float2 at +36)
        u, v = struct.unpack_from('<2f', data, base + 36)
        uvs[vi] = (u, 1.0 - v)  # Flip V for OpenGL convention

    mesh.positions = positions
    mesh.normals = normals
    mesh.uvs = uvs

    # Extract indices (uint16 triangle list)
    raw_indices = np.frombuffer(data[idata_off:idata_off + index_count * 2], dtype=np.uint16)
    mesh.indices = raw_indices.astype(np.uint32)

    return mesh


def meshes_to_glb(meshes, output_path):
    """Convert a list of MeshData objects to a GLB file.

    Uses the GLTF 2.0 binary format directly (no trimesh dependency needed).
    Each mesh becomes a separate node with shader_index in extras for texture mapping.
    """
    if not meshes:
        return False

    accessors = []
    buffer_views = []
    binary_chunks = []
    byte_offset = 0

    # Each mesh becomes its own GLTF mesh + node
    gltf_meshes = []
    gltf_nodes = []
    root_children = []

    for mi, mesh in enumerate(meshes):
        if mesh.positions is None or mesh.indices is None:
            continue
        if len(mesh.positions) == 0 or len(mesh.indices) == 0:
            continue

        # --- Index buffer ---
        idx_data = mesh.indices.astype(np.uint32).tobytes()
        pad = (4 - len(idx_data) % 4) % 4
        idx_data_padded = idx_data + b'\x00' * pad

        idx_bv = len(buffer_views)
        buffer_views.append({
            'buffer': 0,
            'byteOffset': byte_offset,
            'byteLength': len(idx_data),
            'target': 34963  # ELEMENT_ARRAY_BUFFER
        })

        idx_acc = len(accessors)
        accessors.append({
            'bufferView': idx_bv,
            'componentType': 5125,  # UNSIGNED_INT
            'count': len(mesh.indices),
            'type': 'SCALAR',
            'max': [int(mesh.indices.max())],
            'min': [int(mesh.indices.min())]
        })

        binary_chunks.append(idx_data_padded)
        byte_offset += len(idx_data_padded)

        # --- Position buffer ---
        pos_data = mesh.positions.astype(np.float32).tobytes()
        pad = (4 - len(pos_data) % 4) % 4
        pos_data_padded = pos_data + b'\x00' * pad

        pos_bv = len(buffer_views)
        buffer_views.append({
            'buffer': 0,
            'byteOffset': byte_offset,
            'byteLength': len(pos_data),
            'target': 34962  # ARRAY_BUFFER
        })

        pos_min = mesh.positions.min(axis=0).tolist()
        pos_max = mesh.positions.max(axis=0).tolist()
        pos_acc = len(accessors)
        accessors.append({
            'bufferView': pos_bv,
            'componentType': 5126,  # FLOAT
            'count': len(mesh.positions),
            'type': 'VEC3',
            'max': pos_max,
            'min': pos_min
        })

        binary_chunks.append(pos_data_padded)
        byte_offset += len(pos_data_padded)

        # --- Normal buffer ---
        attributes = {'POSITION': pos_acc}

        if mesh.normals is not None and len(mesh.normals) > 0:
            nrm_data = mesh.normals.astype(np.float32).tobytes()
            pad = (4 - len(nrm_data) % 4) % 4
            nrm_data_padded = nrm_data + b'\x00' * pad

            nrm_bv = len(buffer_views)
            buffer_views.append({
                'buffer': 0,
                'byteOffset': byte_offset,
                'byteLength': len(nrm_data),
                'target': 34962
            })

            nrm_acc = len(accessors)
            accessors.append({
                'bufferView': nrm_bv,
                'componentType': 5126,
                'count': len(mesh.normals),
                'type': 'VEC3'
            })

            attributes['NORMAL'] = nrm_acc
            binary_chunks.append(nrm_data_padded)
            byte_offset += len(nrm_data_padded)

        # --- UV buffer ---
        if mesh.uvs is not None and len(mesh.uvs) > 0:
            uv_data = mesh.uvs.astype(np.float32).tobytes()
            pad = (4 - len(uv_data) % 4) % 4
            uv_data_padded = uv_data + b'\x00' * pad

            uv_bv = len(buffer_views)
            buffer_views.append({
                'buffer': 0,
                'byteOffset': byte_offset,
                'byteLength': len(uv_data),
                'target': 34962
            })

            uv_acc = len(accessors)
            accessors.append({
                'bufferView': uv_bv,
                'componentType': 5126,
                'count': len(mesh.uvs),
                'type': 'VEC2'
            })

            attributes['TEXCOORD_0'] = uv_acc
            binary_chunks.append(uv_data_padded)
            byte_offset += len(uv_data_padded)

        primitive = {
            'attributes': attributes,
            'indices': idx_acc,
            'mode': 4  # TRIANGLES
        }

        # Each mesh gets its own GLTF mesh and node
        mesh_idx = len(gltf_meshes)
        vert_count = len(mesh.positions)
        tri_count = len(mesh.indices) // 3
        mesh_name = f"part_{mi}_s{mesh.shader_index}_v{vert_count}"

        gltf_meshes.append({
            'primitives': [primitive],
            'name': mesh_name
        })

        node_idx = len(gltf_nodes) + 1  # +1 because root node is index 0
        gltf_nodes.append({
            'mesh': mesh_idx,
            'name': mesh_name,
            'extras': {
                'shader_index': mesh.shader_index,
                'vertex_count': vert_count,
                'triangle_count': tri_count,
                'mesh_index': mi
            }
        })
        root_children.append(node_idx)

    if not gltf_meshes:
        return False

    # Root node is a container for all mesh nodes
    all_nodes = [{'name': 'vehicle', 'children': root_children}] + gltf_nodes

    # Build GLTF JSON
    gltf = {
        'asset': {'version': '2.0', 'generator': 'ragemp-yft-parser'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': all_nodes,
        'meshes': gltf_meshes,
        'accessors': accessors,
        'bufferViews': buffer_views,
        'buffers': [{'byteLength': byte_offset}]
    }

    json_str = json.dumps(gltf, separators=(',', ':'))
    json_bytes = json_str.encode('utf-8')
    # Pad JSON to 4-byte boundary
    json_pad = (4 - len(json_bytes) % 4) % 4
    json_bytes_padded = json_bytes + b' ' * json_pad

    bin_data = b''.join(binary_chunks)
    # Pad binary to 4-byte boundary
    bin_pad = (4 - len(bin_data) % 4) % 4
    bin_data_padded = bin_data + b'\x00' * bin_pad

    # GLB header: magic, version, total length
    total_length = 12 + 8 + len(json_bytes_padded) + 8 + len(bin_data_padded)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'wb') as f:
        # GLB header
        f.write(struct.pack('<III', 0x46546C67, 2, total_length))  # glTF magic
        # JSON chunk
        f.write(struct.pack('<II', len(json_bytes_padded), 0x4E4F534A))  # JSON
        f.write(json_bytes_padded)
        # BIN chunk
        f.write(struct.pack('<II', len(bin_data_padded), 0x004E4942))  # BIN
        f.write(bin_data_padded)

    logger.info(f"  GLB written: {os.path.basename(output_path)} "
                f"({len(gltf_meshes)} meshes, {total_length:,} bytes)")
    return True


def extract_model_from_yft(data, sys_flags, gfx_flags, output_path):
    """Extract a 3D model from decompressed YFT data and save as GLB.

    Args:
        data: Raw decompressed RSC7 data
        sys_flags: System flags
        gfx_flags: Graphics flags
        output_path: Path to write the .glb file

    Returns:
        dict with model info, or None on failure
    """
    meshes = parse_yft(data, sys_flags, gfx_flags)
    if not meshes:
        logger.warning("  No geometry found in YFT")
        return None

    total_verts = sum(len(m.positions) for m in meshes if m.positions is not None)
    total_tris = sum(len(m.indices) // 3 for m in meshes if m.indices is not None)

    if not meshes_to_glb(meshes, output_path):
        return None

    return {
        'file': os.path.basename(output_path),
        'path': output_path,
        'meshes': len(meshes),
        'vertices': total_verts,
        'triangles': total_tris,
    }
