"""
Blender Batch Processing Script
Run with: blender --background --python batch_process.py -- --input <dir> --output <dir>

Processes 3D models:
- Fixes scale to GTA V standard
- Applies transforms
- Auto UV unwrap if missing
- Exports to FBX for further GTA conversion
"""

import bpy
import os
import sys
import argparse
import math


def parse_args():
    """Parse arguments after the -- separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Blender batch model processor")
    parser.add_argument("--input", required=True, help="Input directory with models")
    parser.add_argument("--output", required=True, help="Output directory for processed models")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale factor")
    parser.add_argument("--format", choices=["fbx", "obj", "gltf"], default="fbx", help="Export format")
    return parser.parse_args(argv)


def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


def import_model(filepath):
    """Import a model file based on its extension."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=filepath)
    elif ext == ".obj":
        bpy.ops.import_scene.obj(filepath=filepath)
    elif ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=filepath)
    else:
        print(f"Unsupported format: {ext}")
        return False
    return True


def fix_scale(scale_factor=1.0):
    """Normalize scale for all mesh objects."""
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.scale = (scale_factor, scale_factor, scale_factor)
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            obj.select_set(False)


def auto_uv_unwrap():
    """Apply smart UV project to meshes that lack UV maps."""
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        if len(obj.data.uv_layers) == 0:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(66))
            bpy.ops.object.mode_set(mode="OBJECT")
            obj.select_set(False)
            print(f"  UV unwrapped: {obj.name}")


def optimize_mesh():
    """Basic mesh cleanup."""
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Remove doubles
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=0.001)
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")

        obj.select_set(False)


def export_model(output_path, export_format="fbx"):
    """Export the processed model."""
    bpy.ops.object.select_all(action="SELECT")

    if export_format == "fbx":
        bpy.ops.export_scene.fbx(
            filepath=output_path + ".fbx",
            use_selection=True,
            apply_scale_options="FBX_SCALE_ALL",
            axis_forward="-Z",
            axis_up="Y"
        )
    elif export_format == "obj":
        bpy.ops.export_scene.obj(
            filepath=output_path + ".obj",
            use_selection=True
        )
    elif export_format == "gltf":
        bpy.ops.export_scene.gltf(
            filepath=output_path + ".glb",
            use_selection=True,
            export_format="GLB"
        )


def process_model(input_path, output_path, scale_factor, export_format):
    """Full processing pipeline for a single model."""
    print(f"\nProcessing: {input_path}")
    clear_scene()

    if not import_model(input_path):
        return False

    fix_scale(scale_factor)
    auto_uv_unwrap()
    optimize_mesh()
    export_model(output_path, export_format)

    print(f"Exported: {output_path}.{export_format}")
    return True


def main():
    args = parse_args()
    input_dir = args.input
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    supported = (".fbx", ".obj", ".gltf", ".glb", ".dae")
    model_files = []

    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f.lower().endswith(supported):
                model_files.append(os.path.join(root, f))

    print(f"Found {len(model_files)} models to process")

    success = 0
    failed = 0
    for filepath in model_files:
        name = os.path.splitext(os.path.basename(filepath))[0]
        output_path = os.path.join(output_dir, name)

        if process_model(filepath, output_path, args.scale, args.format):
            success += 1
        else:
            failed += 1

    print(f"\nBatch complete: {success} processed, {failed} failed")


if __name__ == "__main__":
    main()
