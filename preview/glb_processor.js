/**
 * GLB Processor - Embeds textures into GLB files and removes logo meshes.
 * Uses @gltf-transform/core for reliable GLB manipulation.
 * 
 * Usage:
 *   node glb_processor.js embed <glb_path> <textures_dir> [output_path]
 *   node glb_processor.js remove-logos <glb_path> [output_path]
 *   node glb_processor.js process <preview_dir>  (embed + logo remove for a preview folder)
 */

const fs = require('fs');
const path = require('path');
const { Document, NodeIO, Buffer: GltfBuffer } = require('@gltf-transform/core');

// Logo/brand mesh name patterns to remove
const LOGO_PATTERNS = [
    /logo/i, /emblem/i, /badge/i, /brand/i, /decal/i,
    /sign_\d/i, /livery/i, /plate/i, /sticker/i,
    /manufacturer/i, /nameplate/i
];

/**
 * Read a GLB file and return a gltf-transform Document.
 */
async function readGLB(glbPath) {
    const io = new NodeIO();
    return await io.read(glbPath);
}

/**
 * Write a gltf-transform Document to a GLB file.
 */
async function writeGLB(doc, outputPath) {
    const io = new NodeIO();
    await io.write(outputPath, doc);
}

/**
 * Embed PNG textures into a GLB file's materials.
 * Maps textures to meshes using shader_index from extras or by naming convention.
 */
async function embedTextures(glbPath, texturesDir, outputPath) {
    if (!fs.existsSync(glbPath)) {
        throw new Error(`GLB not found: ${glbPath}`);
    }
    if (!fs.existsSync(texturesDir)) {
        throw new Error(`Textures dir not found: ${texturesDir}`);
    }

    const doc = await readGLB(glbPath);
    const root = doc.getRoot();

    // Find all PNG textures
    const texFiles = fs.readdirSync(texturesDir)
        .filter(f => /\.(png|jpg|jpeg)$/i.test(f))
        .sort();

    if (texFiles.length === 0) {
        console.log('No textures found to embed');
        await writeGLB(doc, outputPath || glbPath);
        return { embedded: 0 };
    }

    // Categorize textures by GTA V naming conventions
    const isDiffuse = n => /(_d\.|_d_|_diff|_diffuse|_col|_color|_tex\.|_whi\.|_uni\.)/i.test(n)
        && !/(_n\.|_n_|_nm|_nrm|_normal|_bump|_spec|_s\.)/i.test(n);
    const isNormal = n => /(_n\.|_n_|_nm\.|_nrm|_normal|_bump)/i.test(n);
    const isSpec = n => /(_s\.|_s_|_spec|_material)/i.test(n);

    const diffuseFiles = texFiles.filter(isDiffuse);
    const normalFiles = texFiles.filter(isNormal);
    const specFiles = texFiles.filter(isSpec);
    // If no categorized textures, treat all as diffuse
    const effectiveDiffuse = diffuseFiles.length > 0 ? diffuseFiles : texFiles.filter(f => !isNormal(f) && !isSpec(f));

    console.log(`Textures: ${texFiles.length} total, ${effectiveDiffuse.length} diffuse, ${normalFiles.length} normal, ${specFiles.length} spec`);

    // Create gltf-transform textures from files
    const createTexture = (filePath, name) => {
        const data = fs.readFileSync(filePath);
        const ext = path.extname(filePath).toLowerCase();
        const mimeType = ext === '.png' ? 'image/png' : 'image/jpeg';
        const tex = doc.createTexture(name)
            .setImage(new Uint8Array(data))
            .setMimeType(mimeType);
        return tex;
    };

    // Find matching normal map for a diffuse texture
    const findNormal = (diffName) => {
        const base = diffName.replace(/(_d|_diff|_diffuse|_tex|_col|_color|_whi|_uni|_\d+)\.\w+$/i, '');
        return normalFiles.find(n => {
            const nb = n.replace(/(_n|_nm|_nrm|_normal|_bump)\.\w+$/i, '');
            return nb.toLowerCase() === base.toLowerCase();
        });
    };

    // Get all meshes and their primitives
    const meshes = root.listMeshes();
    let embedded = 0;

    if (meshes.length === 0) {
        console.log('No meshes in GLB');
        await writeGLB(doc, outputPath || glbPath);
        return { embedded: 0 };
    }

    // Strategy 1: Map by shader_index from extras
    const nodes = root.listNodes();
    let usedShaderIndex = false;

    for (const node of nodes) {
        const extras = node.getExtras();
        const si = extras?.shader_index;
        if (si !== undefined && si >= 0 && si < effectiveDiffuse.length) {
            const mesh = node.getMesh();
            if (!mesh) continue;

            const diffFile = effectiveDiffuse[si];
            const diffPath = path.join(texturesDir, diffFile);
            const diffTex = createTexture(diffPath, path.basename(diffFile, path.extname(diffFile)));

            // Create material with embedded texture
            const mat = doc.createMaterial(diffFile.replace(/\.\w+$/, ''))
                .setBaseColorTexture(diffTex)
                .setMetallicFactor(0.4)
                .setRoughnessFactor(0.5);

            // Try to find and add normal map
            const normFile = findNormal(diffFile);
            if (normFile) {
                const normPath = path.join(texturesDir, normFile);
                const normTex = createTexture(normPath, path.basename(normFile, path.extname(normFile)));
                mat.setNormalTexture(normTex);
            }

            for (const prim of mesh.listPrimitives()) {
                prim.setMaterial(mat);
            }
            embedded++;
            usedShaderIndex = true;
            console.log(`  shader_index ${si} -> ${diffFile}`);
        }
    }

    // Strategy 2: If no shader_index, distribute textures across meshes
    if (!usedShaderIndex && effectiveDiffuse.length > 0) {
        console.log('Using round-robin texture assignment');
        let texIdx = 0;
        for (const mesh of meshes) {
            if (texIdx >= effectiveDiffuse.length) texIdx = 0;
            const diffFile = effectiveDiffuse[texIdx];
            const diffPath = path.join(texturesDir, diffFile);
            const diffTex = createTexture(diffPath, path.basename(diffFile, path.extname(diffFile)));

            const mat = doc.createMaterial(diffFile.replace(/\.\.w+$/, ''))
                .setBaseColorTexture(diffTex)
                .setMetallicFactor(0.4)
                .setRoughnessFactor(0.5);

            const normFile = findNormal(diffFile);
            if (normFile) {
                const normPath = path.join(texturesDir, normFile);
                const normTex = createTexture(normPath, path.basename(normFile, path.extname(normFile)));
                mat.setNormalTexture(normTex);
            }

            for (const prim of mesh.listPrimitives()) {
                prim.setMaterial(mat);
            }
            embedded++;
            texIdx++;
        }
    }

    // Strategy 3: Assign default materials to any meshes still without a material
    // GTA V vehicles have procedural shaders (car paint, glass, chrome) that don't use textures
    const defaultPaint = doc.createMaterial('default_carpaint')
        .setBaseColorFactor([0.85, 0.85, 0.87, 1.0])  // light silver
        .setMetallicFactor(0.9)
        .setRoughnessFactor(0.25);
    const defaultGlass = doc.createMaterial('default_glass')
        .setBaseColorFactor([0.15, 0.18, 0.22, 0.35])
        .setAlphaMode('BLEND')
        .setMetallicFactor(0.1)
        .setRoughnessFactor(0.05);
    const defaultChrome = doc.createMaterial('default_chrome')
        .setBaseColorFactor([0.75, 0.75, 0.78, 1.0])
        .setMetallicFactor(1.0)
        .setRoughnessFactor(0.1);
    const defaultBlack = doc.createMaterial('default_black')
        .setBaseColorFactor([0.05, 0.05, 0.05, 1.0])
        .setMetallicFactor(0.3)
        .setRoughnessFactor(0.6);

    let defaultAssigned = 0;
    for (const node of nodes) {
        const mesh = node.getMesh();
        if (!mesh) continue;
        for (const prim of mesh.listPrimitives()) {
            if (prim.getMaterial()) continue;
            // Heuristic: use vertex count and mesh name to guess material type
            const meshName = mesh.getName() || '';
            const extras = node.getExtras();
            const verts = extras?.vertex_count || 0;
            // Large meshes are typically body panels
            if (verts > 5000) {
                prim.setMaterial(defaultPaint);
            } else if (verts > 2000) {
                // Medium meshes: could be trim, grills, etc
                prim.setMaterial(defaultChrome);
            } else if (verts > 500) {
                prim.setMaterial(defaultBlack);
            } else {
                // Small meshes: misc parts
                prim.setMaterial(defaultGlass);
            }
            defaultAssigned++;
        }
    }
    if (defaultAssigned > 0) {
        console.log(`  Assigned default materials to ${defaultAssigned} unmapped primitives`);
    }

    const out = outputPath || glbPath.replace('.glb', '_textured.glb');
    await writeGLB(doc, out);
    console.log(`Embedded ${embedded} materials, saved: ${out}`);
    return { embedded, defaultAssigned, output: out };
}

/**
 * Remove logo/brand meshes from a GLB file.
 */
async function removeLogos(glbPath, outputPath) {
    const doc = await readGLB(glbPath);
    const root = doc.getRoot();
    let removed = 0;

    for (const node of root.listNodes()) {
        const name = node.getName() || '';
        const mesh = node.getMesh();
        if (!mesh) continue;

        const isLogo = LOGO_PATTERNS.some(pat => pat.test(name));
        if (isLogo) {
            console.log(`  Removing logo mesh: ${name}`);
            node.setMesh(null);
            removed++;
        }
    }

    // Also check mesh names directly
    for (const mesh of root.listMeshes()) {
        const name = mesh.getName() || '';
        const isLogo = LOGO_PATTERNS.some(pat => pat.test(name));
        if (isLogo) {
            // Remove all primitives from logo meshes
            for (const prim of mesh.listPrimitives()) {
                prim.dispose();
            }
            removed++;
            console.log(`  Removed logo mesh primitives: ${name}`);
        }
    }

    const out = outputPath || glbPath.replace('.glb', '_clean.glb');
    await writeGLB(doc, out);
    console.log(`Removed ${removed} logo elements, saved: ${out}`);
    return { removed, output: out };
}

/**
 * Rotate model geometry from Z-up (GTA V) to Y-up (glTF/model-viewer).
 * Applies a -90 degree rotation around X axis to all root scene nodes.
 */
async function rotateZupToYup(doc) {
    const root = doc.getRoot();
    const scenes = root.listScenes();
    // Quaternion for -90deg rotation around X: [-sin(45), 0, 0, cos(45)]
    // Maps: GTA Z-up -> glTF Y-up, GTA Y-forward -> glTF -Z (forward)
    const q = [-0.7071068, 0, 0, 0.7071068];

    for (const scene of scenes) {
        for (const node of scene.listChildren()) {
            const existing = node.getRotation(); // [x, y, z, w]
            // Multiply quaternions: q * existing
            const result = multiplyQuat(q, existing);
            node.setRotation(result);
        }
    }
    console.log('  Applied Z-up -> Y-up rotation');
}

// Quaternion multiplication: a * b
function multiplyQuat(a, b) {
    return [
        a[3]*b[0] + a[0]*b[3] + a[1]*b[2] - a[2]*b[1],
        a[3]*b[1] - a[0]*b[2] + a[1]*b[3] + a[2]*b[0],
        a[3]*b[2] + a[0]*b[1] - a[1]*b[0] + a[2]*b[3],
        a[3]*b[3] - a[0]*b[0] - a[1]*b[1] - a[2]*b[2],
    ];
}

/**
 * Process a full preview directory: embed textures + optionally remove logos.
 * Expects: <preview_dir>/models/*.glb and <preview_dir>/textures/*.png
 */
async function processPreviewDir(previewDir, options = {}) {
    const modelsDir = path.join(previewDir, 'models');
    const texturesDir = path.join(previewDir, 'textures');

    if (!fs.existsSync(modelsDir)) {
        return { error: 'No models directory found' };
    }

    const glbFiles = fs.readdirSync(modelsDir).filter(f => f.endsWith('.glb') && !f.endsWith('_textured.glb') && !f.endsWith('_clean.glb'));

    if (glbFiles.length === 0) {
        return { error: 'No GLB files found' };
    }

    const results = [];

    for (const glbFile of glbFiles) {
        const glbPath = path.join(modelsDir, glbFile);
        const texturedPath = path.join(modelsDir, glbFile.replace('.glb', '_textured.glb'));
        
        try {
            // Step 1: Embed textures
            if (fs.existsSync(texturesDir)) {
                const embedResult = await embedTextures(glbPath, texturesDir, texturedPath);
                results.push({ file: glbFile, ...embedResult });
            } else {
                // No textures, just copy
                fs.copyFileSync(glbPath, texturedPath);
                results.push({ file: glbFile, embedded: 0, output: texturedPath });
            }

            // Step 1b: Apply Z-up -> Y-up rotation
            try {
                const rotDoc = await readGLB(texturedPath);
                await rotateZupToYup(rotDoc);
                await writeGLB(rotDoc, texturedPath);
                console.log(`  Rotated ${glbFile} (Z-up -> Y-up)`);
            } catch (re) {
                console.error(`  Rotation failed for ${glbFile}: ${re.message}`);
            }

            // Step 2: Remove logos if requested
            if (options.removeLogos) {
                const cleanPath = path.join(modelsDir, glbFile.replace('.glb', '_clean.glb'));
                const logoResult = await removeLogos(texturedPath, cleanPath);
                results[results.length - 1].logos_removed = logoResult.removed;
            }
        } catch (e) {
            console.error(`Error processing ${glbFile}: ${e.message}`);
            results.push({ file: glbFile, error: e.message });
        }
    }

    // Update manifest to point to textured GLB
    const manifestPath = path.join(previewDir, 'manifest.json');
    if (fs.existsSync(manifestPath)) {
        try {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
            if (manifest.models) {
                for (const model of manifest.models) {
                    const texturedName = model.name.replace('.glb', '_textured.glb');
                    const texturedFile = path.join(modelsDir, texturedName);
                    if (fs.existsSync(texturedFile)) {
                        model.textured_path = `models/${texturedName}`;
                    }
                }
            }
            fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
        } catch (e) {
            console.error(`Failed to update manifest: ${e.message}`);
        }
    }

    return { processed: results.length, results };
}

// CLI interface
async function main() {
    const args = process.argv.slice(2);
    const command = args[0];

    try {
        switch (command) {
            case 'embed': {
                const [, glbPath, texDir, outPath] = args;
                if (!glbPath || !texDir) {
                    console.error('Usage: node glb_processor.js embed <glb> <textures_dir> [output]');
                    process.exit(1);
                }
                const result = await embedTextures(glbPath, texDir, outPath);
                console.log(JSON.stringify(result));
                break;
            }
            case 'remove-logos': {
                const [, glbPath, outPath] = args;
                if (!glbPath) {
                    console.error('Usage: node glb_processor.js remove-logos <glb> [output]');
                    process.exit(1);
                }
                const result = await removeLogos(glbPath, outPath);
                console.log(JSON.stringify(result));
                break;
            }
            case 'process': {
                const [, previewDir, ...flags] = args;
                if (!previewDir) {
                    console.error('Usage: node glb_processor.js process <preview_dir> [--remove-logos]');
                    process.exit(1);
                }
                const opts = { removeLogos: flags.includes('--remove-logos') };
                const result = await processPreviewDir(previewDir, opts);
                console.log(JSON.stringify(result, null, 2));
                break;
            }
            case 'rotate': {
                // Batch rotate GLBs: node glb_processor.js rotate <dir_or_file>
                const [, target] = args;
                if (!target) {
                    console.error('Usage: node glb_processor.js rotate <glb_file_or_preview_dir>');
                    process.exit(1);
                }
                if (target.endsWith('.glb')) {
                    const doc = await readGLB(target);
                    await rotateZupToYup(doc);
                    await writeGLB(doc, target);
                    console.log(`Rotated: ${target}`);
                } else {
                    // Treat as preview root dir, find all _textured.glb recursively
                    const glob = require('fs');
                    function findGlbs(dir) {
                        let results = [];
                        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
                            const full = path.join(dir, entry.name);
                            if (entry.isDirectory()) results = results.concat(findGlbs(full));
                            else if (entry.name.endsWith('_textured.glb')) results.push(full);
                        }
                        return results;
                    }
                    const files = findGlbs(target);
                    console.log(`Found ${files.length} textured GLBs to rotate`);
                    for (const f of files) {
                        try {
                            const doc = await readGLB(f);
                            await rotateZupToYup(doc);
                            await writeGLB(doc, f);
                            console.log(`  OK: ${path.relative(target, f)}`);
                        } catch (e) {
                            console.error(`  FAIL: ${path.relative(target, f)}: ${e.message}`);
                        }
                    }
                    console.log('Done');
                }
                break;
            }
            default:
                console.error('Commands: embed, remove-logos, process, rotate');
                process.exit(1);
        }
    } catch (e) {
        console.error(`Error: ${e.message}`);
        process.exit(1);
    }
}

// Export for use as module
module.exports = { embedTextures, removeLogos, processPreviewDir };

if (require.main === module) {
    main();
}
