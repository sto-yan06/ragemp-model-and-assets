/**
 * RageMP Resource Builder
 * 
 * Builds the client_packages stream folder structure from processed GTA assets.
 * Creates proper resource directories for RageMP server streaming.
 * 
 * Structure:
 *   client_packages/
 *     vehicles/stream/
 *     weapons/stream/
 *     clothes/stream/
 *     houses/stream/
 */

const fs = require("fs-extra");
const path = require("path");
const glob = require("glob");

const CONFIG_PATH = path.join(__dirname, "..", "config.json");

function loadConfig() {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
}

function log(msg) {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] ${msg}`);
}

/**
 * Maps file extensions to resource categories
 */
const CATEGORY_MAP = {
    ".yft": "vehicles",
    ".ydr": "weapons",
    ".ydd": "clothes",
    ".ymap": "houses",
    ".ytyp": "houses",
    ".ytd": null, // determined by context
    ".meta": null,
};

/**
 * Determine the category for a .ytd file by checking sibling files
 */
function determineYtdCategory(filePath) {
    const dir = path.dirname(filePath);
    const baseName = path.parse(filePath).name;

    try {
        const siblings = fs.readdirSync(dir);
        for (const sibling of siblings) {
            const siblingBase = path.parse(sibling).name;
            const siblingExt = path.extname(sibling).toLowerCase();

            if (siblingBase === baseName) {
                if (siblingExt === ".yft") return "vehicles";
                if (siblingExt === ".ydr") return "weapons";
                if (siblingExt === ".ydd") return "clothes";
                if (siblingExt === ".ymap" || siblingExt === ".ytyp") return "houses";
            }
        }
    } catch (e) {
        // Directory read failed
    }

    return "vehicles"; // default
}

/**
 * Build stream folders for all categories
 */
function buildStreamFolders(config) {
    const sourceDir = config.resource_builder.source_dir;
    const targetDir = config.resource_builder.target_dir;
    const categories = config.resource_builder.categories;
    const limits = config.limits;

    // Create target directories
    for (const category of categories) {
        const streamDir = path.join(targetDir, category, "stream");
        fs.ensureDirSync(streamDir);
        log(`Created stream dir: ${streamDir}`);
    }

    const stats = {};
    for (const cat of categories) {
        stats[cat] = { copied: 0, skipped: 0, errors: 0 };
    }

    // Limit keys
    const limitKeys = {
        vehicles: "max_vehicles",
        weapons: "max_weapons",
        clothes: "max_clothes",
        houses: "max_houses",
    };

    // Walk the source directory
    if (!fs.existsSync(sourceDir)) {
        log(`Source directory not found: ${sourceDir}`);
        log("Run the converter first to populate GTA-ready assets.");
        return stats;
    }

    const allFiles = [];
    function walkDir(dir) {
        try {
            const entries = fs.readdirSync(dir, { withFileTypes: true });
            for (const entry of entries) {
                const fullPath = path.join(dir, entry.name);
                if (entry.isDirectory()) {
                    walkDir(fullPath);
                } else {
                    allFiles.push(fullPath);
                }
            }
        } catch (e) {
            log(`Error reading directory ${dir}: ${e.message}`);
        }
    }

    walkDir(sourceDir);
    log(`Found ${allFiles.length} files in source directory`);

    // Also collect from the assets sorted directories
    const assetsDir = path.join(__dirname, "..", "assets");
    if (fs.existsSync(assetsDir)) {
        walkDir(assetsDir);
        log(`Total files including assets: ${allFiles.length}`);
    }

    // Process each file
    for (const filePath of allFiles) {
        const ext = path.extname(filePath).toLowerCase();
        let category = CATEGORY_MAP[ext];

        if (category === undefined) continue; // unsupported extension
        if (category === null) {
            if (ext === ".ytd") {
                category = determineYtdCategory(filePath);
            } else if (ext === ".meta") {
                // .meta files go alongside their model category
                category = determineYtdCategory(filePath);
            } else {
                continue;
            }
        }

        if (!categories.includes(category)) continue;

        // Check limits
        const limitKey = limitKeys[category];
        const maxCount = limits[limitKey] || Infinity;
        if (stats[category].copied >= maxCount) {
            stats[category].skipped++;
            continue;
        }

        // Copy to stream folder
        const fileName = path.basename(filePath);
        const targetPath = path.join(targetDir, category, "stream", fileName);

        try {
            if (!fs.existsSync(targetPath)) {
                fs.copySync(filePath, targetPath);
                stats[category].copied++;
            } else {
                stats[category].skipped++; // already exists
            }
        } catch (e) {
            log(`Error copying ${fileName}: ${e.message}`);
            stats[category].errors++;
        }
    }

    return stats;
}

/**
 * Generate index.js for each resource category (RageMP client-side loader)
 */
function generateResourceLoaders(config) {
    const targetDir = config.resource_builder.target_dir;
    const categories = config.resource_builder.categories;

    for (const category of categories) {
        const categoryDir = path.join(targetDir, category);
        const streamDir = path.join(categoryDir, "stream");

        if (!fs.existsSync(streamDir)) continue;

        const files = fs.readdirSync(streamDir);
        if (files.length === 0) continue;

        // Generate resource index
        const indexContent = `// Auto-generated RageMP resource loader for ${category}
// Generated: ${new Date().toISOString()}
// Files: ${files.length}

const streamFiles = ${JSON.stringify(files, null, 2)};

module.exports = {
    category: "${category}",
    files: streamFiles,
    count: streamFiles.length
};
`;

        fs.writeFileSync(path.join(categoryDir, "index.js"), indexContent);
        log(`Generated index.js for ${category} (${files.length} files)`);
    }
}

/**
 * Generate build manifest
 */
function generateBuildManifest(config, stats) {
    const targetDir = config.resource_builder.target_dir;

    const manifest = {
        build_time: new Date().toISOString(),
        categories: {},
        total_files: 0,
        total_size_mb: 0,
    };

    for (const [category, stat] of Object.entries(stats)) {
        const streamDir = path.join(targetDir, category, "stream");
        let totalSize = 0;
        let fileCount = 0;

        if (fs.existsSync(streamDir)) {
            const files = fs.readdirSync(streamDir);
            fileCount = files.length;
            for (const f of files) {
                try {
                    const fstat = fs.statSync(path.join(streamDir, f));
                    totalSize += fstat.size;
                } catch (e) { }
            }
        }

        manifest.categories[category] = {
            files: fileCount,
            copied_this_run: stat.copied,
            skipped: stat.skipped,
            errors: stat.errors,
            size_mb: Math.round(totalSize / (1024 * 1024) * 100) / 100,
        };

        manifest.total_files += fileCount;
        manifest.total_size_mb += totalSize / (1024 * 1024);
    }

    manifest.total_size_mb = Math.round(manifest.total_size_mb * 100) / 100;

    const manifestPath = path.join(targetDir, "build_manifest.json");
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    log(`Build manifest written to ${manifestPath}`);

    return manifest;
}

// ── Main ──

function main() {
    const config = loadConfig();

    log("=".repeat(60));
    log("RageMP Resource Builder - Starting");
    log("=".repeat(60));

    // Build stream folders
    log("\n--- Building stream folders ---");
    const stats = buildStreamFolders(config);

    // Report
    log("\n--- Build Summary ---");
    for (const [category, stat] of Object.entries(stats)) {
        log(`  ${category}: ${stat.copied} copied, ${stat.skipped} skipped, ${stat.errors} errors`);
    }

    // Generate resource loaders
    log("\n--- Generating resource loaders ---");
    generateResourceLoaders(config);

    // Generate manifest
    log("\n--- Generating build manifest ---");
    const manifest = generateBuildManifest(config, stats);

    log(`\nTotal files: ${manifest.total_files}`);
    log(`Total size: ${manifest.total_size_mb} MB`);
    log("Resource build complete.");
}

main();
