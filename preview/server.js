/**
 * Asset Preview Dashboard Server
 * 
 * Serves a visual preview of all downloaded assets with thumbnails,
 * metadata, filtering, and file details.
 * 
 * Usage:
 *   node preview/server.js
 *   python run.py --preview
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const url = require("url");
const { execFile } = require("child_process");

const ROOT_DIR = path.join(__dirname, "..");
const CONFIG_PATH = path.join(ROOT_DIR, "config.json");
const METADATA_PATH = path.join(ROOT_DIR, "downloads", "_metadata", "asset_index.json");

function loadConfig() {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
}

function loadAssetIndex() {
    if (fs.existsSync(METADATA_PATH)) {
        return JSON.parse(fs.readFileSync(METADATA_PATH, "utf8"));
    }
    return { assets: [], last_updated: null };
}

/**
 * Find the dlc.rpf path for a given vehicle safeName.
 * Checks multiple locations in priority order.
 * Returns the full path or null if not found.
 */
function findRpfPath(safeName) {
    const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);

    // 1. manifest.rpf_source (set during extraction)
    const manifestPath = path.join(previewDir, "manifest.json");
    if (fs.existsSync(manifestPath)) {
        try {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
            if (manifest.rpf_source && fs.existsSync(manifest.rpf_source)) {
                return manifest.rpf_source;
            }
        } catch (e) {}
    }

    // 2. original/dlc.rpf (standard extraction location)
    let rpfPath = path.join(previewDir, "original", "dlc.rpf");
    if (fs.existsSync(rpfPath)) return rpfPath;

    // 3. dlc.rpf in preview dir root
    rpfPath = path.join(previewDir, "dlc.rpf");
    if (fs.existsSync(rpfPath)) return rpfPath;

    // 4. rpf_files path from manifest
    if (fs.existsSync(manifestPath)) {
        try {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
            const rpfEntry = (manifest.rpf_files || []).find(r => r.name.toLowerCase() === "dlc.rpf");
            if (rpfEntry) {
                rpfPath = path.join(previewDir, "extracted", rpfEntry.path);
                if (fs.existsSync(rpfPath)) return rpfPath;
                rpfPath = path.join(previewDir, rpfEntry.path);
                if (fs.existsSync(rpfPath)) return rpfPath;
            }
        } catch (e) {}
    }

    // 5. Recursive scan of preview dir
    try {
        const files = fs.readdirSync(previewDir, { recursive: true });
        for (const f of files) {
            if (f.toString().toLowerCase().endsWith("dlc.rpf")) {
                return path.join(previewDir, f.toString());
            }
        }
    } catch (e) {}

    return null;
}

/**
 * Scan downloads directory for all files even without metadata
 */
function scanDownloads() {
    const downloadsDir = path.join(ROOT_DIR, "downloads");
    const scanned = [];

    if (!fs.existsSync(downloadsDir)) return scanned;

    const categories = fs.readdirSync(downloadsDir, { withFileTypes: true });
    for (const cat of categories) {
        if (!cat.isDirectory() || cat.name.startsWith("_")) continue;

        const catDir = path.join(downloadsDir, cat.name);
        const files = fs.readdirSync(catDir).filter(f => !f.startsWith("_") && !f.startsWith("."));

        // Check for thumbnails
        const thumbDir = path.join(catDir, "_thumbnails");
        const thumbs = {};
        if (fs.existsSync(thumbDir)) {
            for (const t of fs.readdirSync(thumbDir)) {
                const base = path.parse(t).name;
                thumbs[base] = path.join("downloads", cat.name, "_thumbnails", t);
            }
        }

        for (const file of files) {
            const filePath = path.join(catDir, file);
            const stat = fs.statSync(filePath);
            if (!stat.isFile()) continue;

            const baseName = path.parse(file).name;
            scanned.push({
                filename: file,
                category: cat.name,
                filesize_bytes: stat.size,
                filesize_mb: Math.round(stat.size / (1024 * 1024) * 100) / 100,
                thumbnail_relative: thumbs[baseName] || null,
                downloaded_at: stat.mtime.toISOString(),
            });
        }
    }
    return scanned;
}

/**
 * Merge metadata index with filesystem scan
 */
function getFullAssetList() {
    const index = loadAssetIndex();
    const scanned = scanDownloads();

    // Use index data where available, fall back to scanned data
    const indexByFilename = {};
    for (const asset of index.assets) {
        indexByFilename[asset.filename] = asset;
    }

    const merged = [];
    const seenFilenames = new Set();

    // First add all indexed assets
    for (const asset of index.assets) {
        merged.push(asset);
        seenFilenames.add(asset.filename);
    }

    // Add scanned vehicle files not in the index
    for (const file of scanned) {
        if (!seenFilenames.has(file.filename) && file.category === "vehicles") {
            merged.push({
                id: file.filename,
                name: file.filename.replace(/[_-]/g, " ").replace(/\.\w+$/, ""),
                safe_name: path.parse(file.filename).name,
                category: "vehicles",
                filename: file.filename,
                filesize_bytes: file.filesize_bytes,
                filesize_mb: file.filesize_mb,
                thumbnail_relative: file.thumbnail_relative,
                downloaded_at: file.downloaded_at,
                status: "downloaded",
                source_url: "",
                author: "",
                description: "",
                tags: [],
            });
        }
    }

    // Only return vehicles
    return merged.filter(a => a.category === "vehicles");
}

const MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".dds": "image/vnd-ms.dds",
    ".obj": "text/plain",
    ".mtl": "text/plain",
};

function serveFile(res, filePath) {
    const ext = path.extname(filePath).toLowerCase();
    const mime = MIME_TYPES[ext] || "application/octet-stream";

    try {
        const data = fs.readFileSync(filePath);
        res.writeHead(200, { "Content-Type": mime });
        res.end(data);
    } catch (e) {
        res.writeHead(404);
        res.end("Not found");
    }
}

const config = loadConfig();
const PORT = config.preview?.port || 3000;
const HOST = config.preview?.host || "127.0.0.1";

const server = http.createServer((req, res) => {
    const parsedUrl = url.parse(req.url, true);
    const pathname = parsedUrl.pathname;

    // API: get all assets
    if (pathname === "/api/assets") {
        const assets = getFullAssetList();
        const category = parsedUrl.query.category;
        const filtered = category && category !== "all"
            ? assets.filter(a => a.category === category)
            : assets;

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
            assets: filtered,
            total: assets.length,
            filtered: filtered.length,
            categories: [...new Set(assets.map(a => a.category))],
            last_updated: loadAssetIndex().last_updated,
        }));
        return;
    }

    // API: get stats
    if (pathname === "/api/stats") {
        const assets = getFullAssetList();
        const categories = {};
        let totalSize = 0;

        for (const a of assets) {
            if (!categories[a.category]) {
                categories[a.category] = { count: 0, size_mb: 0 };
            }
            categories[a.category].count++;
            categories[a.category].size_mb += a.filesize_mb || 0;
            totalSize += a.filesize_mb || 0;
        }

        for (const cat of Object.keys(categories)) {
            categories[cat].size_mb = Math.round(categories[cat].size_mb * 100) / 100;
        }

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
            total_assets: assets.length,
            total_size_mb: Math.round(totalSize * 100) / 100,
            categories,
            last_updated: loadAssetIndex().last_updated,
        }));
        return;
    }

    // API: extract preview for an asset
    if (pathname === "/api/extract-preview" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => body += chunk);
        req.on("end", () => {
            try {
                const { safeName } = JSON.parse(body);
                if (!safeName || /[^a-zA-Z0-9_\-]/.test(safeName)) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid asset name" }));
                    return;
                }
                const pythonScript = path.join(ROOT_DIR, "processor", "extract_preview.py");
                execFile("python", [pythonScript, "--asset-id", safeName, "--force"], {
                    timeout: 120000,
                    cwd: ROOT_DIR
                }, (err, stdout, stderr) => {
                    if (err) {
                        console.error("Extract error:", stderr);
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ error: stderr || err.message }));
                        return;
                    }
                    // Find JSON in stdout (last line)
                    const lines = stdout.trim().split("\n");
                    let result = {};
                    for (let i = lines.length - 1; i >= 0; i--) {
                        try { result = JSON.parse(lines[i]); break; } catch (_) {}
                    }
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end(JSON.stringify(result));
                });
            } catch (e) {
                res.writeHead(400, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: "Invalid request body" }));
            }
        });
        return;
    }

    // API: remove logos from asset textures
    if (pathname === "/api/remove-logos" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => body += chunk);
        req.on("end", () => {
            try {
                const { safeName, regions } = JSON.parse(body);
                if (!safeName || /[^a-zA-Z0-9_\-]/.test(safeName)) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid asset name" }));
                    return;
                }
                const args = [path.join(ROOT_DIR, "processor", "logo_remover.py"), "--asset", safeName];
                if (regions) {
                    args.push("--regions", JSON.stringify(regions));
                }
                execFile("python", args, {
                    timeout: 60000,
                    cwd: ROOT_DIR
                }, (err, stdout, stderr) => {
                    if (err) {
                        console.error("Logo removal error:", stderr);
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ error: stderr || err.message }));
                        return;
                    }
                    const lines = stdout.trim().split("\n");
                    let result = {};
                    for (let i = lines.length - 1; i >= 0; i--) {
                        try { result = JSON.parse(lines[i]); break; } catch (_) {}
                    }
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end(JSON.stringify(result));
                });
            } catch (e) {
                res.writeHead(400, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: "Invalid request body" }));
            }
        });
        return;
    }

    // API: get preview manifest for an asset
    if (pathname.startsWith("/api/preview-data/")) {
        const safeName = decodeURIComponent(pathname.slice("/api/preview-data/".length));
        if (/[^a-zA-Z0-9_\-]/.test(safeName)) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "Invalid name" }));
            return;
        }
        const manifestPath = path.join(ROOT_DIR, "downloads", "_previews", safeName, "manifest.json");
        if (fs.existsSync(manifestPath)) {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(manifest));
        } else {
            res.writeHead(404, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "No preview data. Click Extract to generate." }));
        }
        return;
    }

    // ── Handling API ──
    // GET /api/handling-original/:safeName - extract original handling from RPF
    const origHandlingMatch = pathname.match(/^\/api\/handling-original\/(.+)$/);
    if (origHandlingMatch && req.method === "GET") {
        const safeName = decodeURIComponent(origHandlingMatch[1]);
        if (!safeName || safeName.includes("..")) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "Invalid name" }));
            return;
        }

        // Check if we already cached the original handling
        const cachedPath = path.join(ROOT_DIR, "downloads", "_previews", safeName, "handling_original.json");
        if (fs.existsSync(cachedPath)) {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(fs.readFileSync(cachedPath, "utf8"));
            return;
        }

        // Extract from RPF using Python
        const pythonCmd = process.platform === "win32" ? "python" : "python3";
        execFile(pythonCmd, [
            "-c",
            `
import sys, json, os
sys.path.insert(0, '.')
from processor.rpf_packer import extract_handling_from_rpf
import xml.etree.ElementTree as ET

rpf_path = sys.argv[1]
if not os.path.exists(rpf_path):
    print(json.dumps({"error": "RPF not found"}))
    sys.exit(0)

xml_str = extract_handling_from_rpf(rpf_path)
if not xml_str:
    print(json.dumps({"error": "No handling.meta in RPF"}))
    sys.exit(0)

root = ET.fromstring(xml_str)
item = root.find('.//Item[@type="CHandlingData"]')
if item is None:
    print(json.dumps({"error": "No CHandlingData found"}))
    sys.exit(0)

result = {"modelName": "", "fields": {}}
for child in item:
    tag = child.tag
    if tag == "handlingName":
        result["modelName"] = child.text or ""
    elif tag == "SubHandlingData":
        continue
    elif child.attrib:
        if "value" in child.attrib:
            try:
                result["fields"][tag] = float(child.attrib["value"])
            except ValueError:
                result["fields"][tag] = child.attrib["value"]
        elif "x" in child.attrib:
            result["fields"][tag + "X"] = float(child.attrib.get("x", 0))
            result["fields"][tag + "Y"] = float(child.attrib.get("y", 0))
            result["fields"][tag + "Z"] = float(child.attrib.get("z", 0))
    elif child.text and child.text.strip():
        result["fields"][tag] = child.text.strip()

print(json.dumps(result))
`,
            findRpfPath(safeName) || ""
        ], { cwd: ROOT_DIR, timeout: 30000 }, (err, stdout, stderr) => {
            if (err) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: stderr || err.message }));
                return;
            }
            try {
                const result = JSON.parse(stdout.trim());
                // Only cache successful results (not errors)
                if (!result.error) {
                    const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                    if (fs.existsSync(previewDir)) {
                        fs.writeFileSync(cachedPath, JSON.stringify(result, null, 2));
                    }
                }
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify(result));
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: "Failed to parse RPF output" }));
            }
        });
        return;
    }

    // GET /api/handling/:safeName - load saved handling data
    const handlingGetMatch = pathname.match(/^\/api\/handling\/(.+)$/);
    if (handlingGetMatch && req.method === "GET") {
        const safeName = decodeURIComponent(handlingGetMatch[1]);
        if (!safeName || safeName.includes("..")) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "Invalid name" }));
            return;
        }
        const handlingPath = path.join(ROOT_DIR, "downloads", "_previews", safeName, "handling.json");
        if (fs.existsSync(handlingPath)) {
            const data = JSON.parse(fs.readFileSync(handlingPath, "utf8"));
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(data));
        } else {
            res.writeHead(404, { "Content-Type": "application/json" });
            res.end(JSON.stringify({}));
        }
        return;
    }

    // POST /api/handling - save handling data
    if (pathname === "/api/handling" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName, handling } = JSON.parse(body);
                if (!safeName || safeName.includes("..")) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid name" }));
                    return;
                }
                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                if (!fs.existsSync(previewDir)) fs.mkdirSync(previewDir, { recursive: true });
                const handlingPath = path.join(previewDir, "handling.json");
                fs.writeFileSync(handlingPath, JSON.stringify(handling, null, 2));

                // Record change in changes.json for the export/repack pipeline
                const changesPath = path.join(previewDir, "changes.json");
                let changesData = { safe_name: safeName, changes: [], repack_history: [] };
                if (fs.existsSync(changesPath)) {
                    try { changesData = JSON.parse(fs.readFileSync(changesPath, "utf8")); } catch (e) {}
                }
                // Remove previous handling changes, keep latest
                changesData.changes = (changesData.changes || []).filter(c => c.type !== "handling");
                changesData.changes.push({
                    type: "handling",
                    rpf_path: "common/data/handling.meta",
                    modified_file: "handling.json",
                    timestamp: new Date().toISOString(),
                    description: "Handling parameters modified",
                });
                changesData.last_modified = new Date().toISOString();

                // Find original RPF from manifest
                const manifestP = path.join(previewDir, "manifest.json");
                if (!changesData.original_rpf && fs.existsSync(manifestP)) {
                    try {
                        const man = JSON.parse(fs.readFileSync(manifestP, "utf8"));
                        if (man.rpf_source && fs.existsSync(man.rpf_source)) {
                            changesData.original_rpf = man.rpf_source;
                        }
                    } catch (e) {}
                }

                fs.writeFileSync(changesPath, JSON.stringify(changesData, null, 2));
                console.log(`[Handling] Saved handling for ${safeName} (change tracked)`);
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ success: true }));
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // POST /api/rpf/pack-handling - inject handling.meta into dlc.rpf
    if (pathname === "/api/rpf/pack-handling" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName, handlingXml } = JSON.parse(body);
                if (!safeName || safeName.includes("..")) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid name" }));
                    return;
                }

                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);

                // Find RPF using shared helper
                let rpfPath = findRpfPath(safeName);
                if (!rpfPath) {
                    res.writeHead(404, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "dlc.rpf not found. Re-extract the asset first." }));
                    return;
                }
                console.log(`[RPF] Found RPF at: ${rpfPath}`);

                // Write handling.meta XML
                const handlingMetaPath = path.join(previewDir, "handling.meta");
                fs.writeFileSync(handlingMetaPath, handlingXml, "utf8");

                // Call Python packer to inject into RPF
                const pythonCmd = process.platform === "win32" ? "python" : "python3";
                const scriptPath = path.join(ROOT_DIR, "processor", "rpf_packer.py");

                console.log(`[RPF] Packing handling.meta into ${rpfPath}`);
                execFile(pythonCmd, [scriptPath, rpfPath, handlingMetaPath], { cwd: ROOT_DIR, timeout: 60000 }, (err, stdout, stderr) => {
                    if (err) {
                        console.error(`[RPF] Error: ${stderr || err.message}`);
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ error: stderr || err.message }));
                        return;
                    }
                    console.log(`[RPF] Success: ${stdout.trim()}`);
                    res.writeHead(200, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({
                        success: true,
                        message: stdout.trim(),
                        rpfPath: `downloads/_previews/${safeName}/dlc.rpf`
                    }));
                });
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // ── Pipeline API ──
    // POST /api/pipeline/clean-index - remove assets whose files no longer exist
    if (pathname === "/api/pipeline/clean-index" && req.method === "POST") {
        try {
            const index = loadAssetIndex();
            const before = index.assets.length;
            index.assets = index.assets.filter(a => {
                let fp = a.filepath || "";
                // Resolve relative paths
                if (fp && !path.isAbsolute(fp)) {
                    fp = path.join(ROOT_DIR, fp);
                }
                const exists = fp && fs.existsSync(fp);
                if (!exists) {
                    console.log(`[Clean] Removing stale entry: ${a.safe_name} (file: ${fp})`);
                }
                return exists;
            });
            const removed = before - index.assets.length;
            index.last_updated = new Date().toISOString();
            fs.writeFileSync(METADATA_PATH, JSON.stringify(index, null, 2));
            console.log(`[Clean] Removed ${removed} stale entries, ${index.assets.length} remaining`);
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({
                message: `Removed ${removed} stale entries. ${index.assets.length} valid assets remain.`,
                removed, remaining: index.assets.length
            }));
        } catch (e) {
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: e.message }));
        }
        return;
    }

    // POST /api/pipeline/scrape - run the scraper for a category
    if (pathname === "/api/pipeline/scrape" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { category, count } = JSON.parse(body);
                if (category !== "vehicles") {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Only addon vehicles are supported." }));
                    return;
                }
                const n = Math.min(Math.max(parseInt(count) || 5, 1), 50);
                const pythonCmd = process.platform === "win32" ? "python" : "python3";
                const scriptPath = path.join(ROOT_DIR, "scraper", "scrape_assets.py");

                console.log(`[Pipeline] Scraping ${n} ${category}...`);
                res.writeHead(200, { "Content-Type": "application/json" });

                execFile(pythonCmd, [scriptPath, "--category", category, "--count", String(n)], {
                    cwd: ROOT_DIR, timeout: 600000
                }, (err, stdout, stderr) => {
                    // Log result (response already sent)
                    if (err) {
                        console.log(`[Pipeline] Scrape error: ${err.message}`);
                        console.log(stderr);
                    } else {
                        console.log(`[Pipeline] Scrape complete for ${category}`);
                    }
                });

                // Respond immediately — scraping runs in background
                res.end(JSON.stringify({
                    message: `Scraping ${n} ${category} assets in background. Refresh in a minute to see results.`
                }));
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // POST /api/pipeline/extract-all - extract previews for all unprocessed assets
    if (pathname === "/api/pipeline/extract-all" && req.method === "POST") {
        const pythonCmd = process.platform === "win32" ? "python" : "python3";
        const scriptPath = path.join(ROOT_DIR, "processor", "extract_preview.py");

        console.log(`[Pipeline] Extracting all assets...`);

        execFile(pythonCmd, [scriptPath, "--all"], {
            cwd: ROOT_DIR, timeout: 1200000, maxBuffer: 10 * 1024 * 1024
        }, (err, stdout, stderr) => {
            if (err) {
                console.log(`[Pipeline] Extract error: ${err.message}`);
                if (stderr) console.log(`[Pipeline] stderr: ${stderr.slice(-500)}`);
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: err.message, details: stderr ? stderr.slice(-300) : "" }));
                return;
            }

            console.log(`[Pipeline] Extract complete`);
            if (stderr) console.log(`[Pipeline] Logs:\n${stderr.slice(-1000)}`);

            let summary = { processed: 0, total: 0, results: [] };
            try {
                const lines = stdout.trim().split('\n');
                const lastLine = lines[lines.length - 1];
                summary = JSON.parse(lastLine);
                console.log(`[Pipeline] Processed ${summary.processed}/${summary.total} assets`);
            } catch (e) {
                console.log(`[Pipeline] Could not parse summary from stdout`);
            }

            // Auto-embed textures into GLBs after extraction
            const glbProcessor = path.join(__dirname, "glb_processor.js");
            const previewsDir = path.join(ROOT_DIR, "downloads", "_previews");
            if (summary.results && fs.existsSync(previewsDir)) {
                const withModels = summary.results.filter(r => r.has_3d);
                if (withModels.length > 0) {
                    console.log(`[Pipeline] Auto-embedding textures for ${withModels.length} assets with 3D models...`);
                    for (const r of withModels) {
                        const pd = path.join(previewsDir, r.safe_name);
                        if (fs.existsSync(pd)) {
                            try {
                                require('child_process').execFileSync("node", [glbProcessor, "process", pd], {
                                    cwd: ROOT_DIR, timeout: 60000, maxBuffer: 10 * 1024 * 1024
                                });
                                console.log(`[Pipeline]   Embedded: ${r.safe_name}`);
                            } catch (e) {
                                console.log(`[Pipeline]   Embed failed for ${r.safe_name}: ${e.message}`);
                            }
                        }
                    }
                }
            }

            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({
                message: `Extracted ${summary.processed}/${summary.total} assets. ${summary.total - summary.processed} skipped (missing files or already extracted).`,
                ...summary
            }));
        });
        return;
    }

    // POST /api/pipeline/embed-textures - embed textures into GLB for model-viewer
    if (pathname === "/api/pipeline/embed-textures" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName } = JSON.parse(body);
                if (!safeName || safeName.includes("..")) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid name" }));
                    return;
                }
                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                if (!fs.existsSync(previewDir)) {
                    res.writeHead(404, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Preview not found. Extract first." }));
                    return;
                }

                const scriptPath = path.join(__dirname, "glb_processor.js");
                console.log(`[Pipeline] Embedding textures for: ${safeName}`);

                execFile("node", [scriptPath, "process", previewDir], {
                    cwd: ROOT_DIR, timeout: 120000, maxBuffer: 10 * 1024 * 1024
                }, (err, stdout, stderr) => {
                    if (err) {
                        console.log(`[Pipeline] Embed error: ${err.message}`);
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ error: err.message }));
                        return;
                    }
                    try {
                        const result = JSON.parse(stdout.trim().split('\n').pop());
                        console.log(`[Pipeline] Embedded textures for ${safeName}: ${result.processed} models`);
                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify(result));
                    } catch (e) {
                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ message: "Processing complete", stdout: stdout.slice(-500) }));
                    }
                });
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // POST /api/pipeline/remove-logos - remove logo meshes from GLB
    if (pathname === "/api/pipeline/remove-logos" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName } = JSON.parse(body);
                if (!safeName || safeName.includes("..")) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid name" }));
                    return;
                }
                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                if (!fs.existsSync(previewDir)) {
                    res.writeHead(404, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Preview not found." }));
                    return;
                }

                const scriptPath = path.join(__dirname, "glb_processor.js");
                console.log(`[Pipeline] Removing logos for: ${safeName}`);

                execFile("node", [scriptPath, "process", previewDir, "--remove-logos"], {
                    cwd: ROOT_DIR, timeout: 120000, maxBuffer: 10 * 1024 * 1024
                }, (err, stdout, stderr) => {
                    if (err) {
                        console.log(`[Pipeline] Logo removal error: ${err.message}`);
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ error: err.message }));
                        return;
                    }
                    try {
                        const result = JSON.parse(stdout.trim().split('\n').pop());
                        console.log(`[Pipeline] Logo removal for ${safeName}: done`);

                        // Record texture changes in changes.json
                        const chFile = path.join(previewDir, "changes.json");
                        let chData = { safe_name: safeName, changes: [], repack_history: [] };
                        if (fs.existsSync(chFile)) {
                            try { chData = JSON.parse(fs.readFileSync(chFile, "utf8")); } catch (_) {}
                        }
                        // Remove old texture/logo changes, add new ones
                        chData.changes = (chData.changes || []).filter(c => c.type !== "texture");
                        const totalRemoved = (result.results || []).reduce((s, r) => s + (r.logos_removed || 0), 0);
                        if (totalRemoved > 0) {
                            chData.changes.push({
                                type: "texture",
                                texture_name: "logo_meshes",
                                modified_file: "models/",
                                timestamp: new Date().toISOString(),
                                description: `${totalRemoved} logo mesh(es) removed from ${result.processed || 0} model(s)`,
                            });
                            chData.last_modified = new Date().toISOString();
                            fs.writeFileSync(chFile, JSON.stringify(chData, null, 2));
                        }

                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify(result));
                    } catch (e) {
                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ message: "Processing complete" }));
                    }
                });
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // POST /api/save-texture - save edited texture from canvas editor
    if (pathname === "/api/save-texture" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName, textureName, previewPath, imageData } = JSON.parse(body);
                if (!safeName || safeName.includes("..") || !textureName || !imageData) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Missing required fields" }));
                    return;
                }

                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                if (!fs.existsSync(previewDir)) {
                    res.writeHead(404, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Preview directory not found" }));
                    return;
                }

                // Decode base64 PNG data
                const base64 = imageData.replace(/^data:image\/\w+;base64,/, "");
                const buffer = Buffer.from(base64, "base64");

                // Save to the preview path (overwrite the texture preview)
                const targetPath = path.join(previewDir, previewPath);
                const targetDir = path.dirname(targetPath);
                if (!fs.existsSync(targetDir)) fs.mkdirSync(targetDir, { recursive: true });

                // Backup original if not already backed up
                const backupDir = path.join(previewDir, "textures_original");
                const backupPath = path.join(backupDir, textureName);
                if (!fs.existsSync(backupPath) && fs.existsSync(targetPath)) {
                    if (!fs.existsSync(backupDir)) fs.mkdirSync(backupDir, { recursive: true });
                    fs.copyFileSync(targetPath, backupPath);
                    console.log(`[Texture] Backed up original: ${textureName}`);
                }

                // Write edited texture
                fs.writeFileSync(targetPath, buffer);
                console.log(`[Texture] Saved edited texture: ${textureName} (${buffer.length} bytes)`);

                // Record change in changes.json
                const changesPath = path.join(previewDir, "changes.json");
                let changesData = { safe_name: safeName, changes: [], repack_history: [] };
                if (fs.existsSync(changesPath)) {
                    try { changesData = JSON.parse(fs.readFileSync(changesPath, "utf8")); } catch (e) {}
                }
                // Remove previous entry for same texture, add new
                changesData.changes = (changesData.changes || []).filter(
                    c => !(c.type === "texture" && c.texture_name === textureName)
                );
                changesData.changes.push({
                    type: "texture",
                    texture_name: textureName,
                    modified_file: previewPath,
                    original_backup: `textures_original/${textureName}`,
                    timestamp: new Date().toISOString(),
                    description: `Texture manually edited: ${textureName}`,
                });
                changesData.last_modified = new Date().toISOString();

                // Find original RPF from manifest if not set
                const manifestP = path.join(previewDir, "manifest.json");
                if (!changesData.original_rpf && fs.existsSync(manifestP)) {
                    try {
                        const man = JSON.parse(fs.readFileSync(manifestP, "utf8"));
                        if (man.rpf_source && fs.existsSync(man.rpf_source)) {
                            changesData.original_rpf = man.rpf_source;
                        }
                    } catch (e) {}
                }

                fs.writeFileSync(changesPath, JSON.stringify(changesData, null, 2));

                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ success: true, size: buffer.length, texture: textureName }));
            } catch (e) {
                console.log(`[Texture] Save error: ${e.message}`);
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // GET /api/changes?safeName=xxx - get tracked changes for an asset
    if (pathname === "/api/changes" && req.method === "GET") {
        const safeName = parsedUrl.query.safeName;
        if (!safeName || safeName.includes("..")) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "Invalid name" }));
            return;
        }
        const changesFile = path.join(ROOT_DIR, "downloads", "_previews", safeName, "changes.json");
        // Always try to find the RPF regardless of changes.json state
        const foundRpf = findRpfPath(safeName);

        if (fs.existsSync(changesFile)) {
            try {
                const data = JSON.parse(fs.readFileSync(changesFile, "utf8"));
                const changes = data.changes || [];
                const handling = changes.filter(c => c.type === "handling");
                const textures = changes.filter(c => c.type === "texture");
                const rpfPath = data.original_rpf && fs.existsSync(data.original_rpf)
                    ? data.original_rpf : foundRpf;
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({
                    total: changes.length,
                    handling_changes: handling.length,
                    texture_changes: textures.length,
                    changes,
                    original_rpf: rpfPath || null,
                    original_rpf_exists: !!rpfPath,
                    last_modified: data.last_modified,
                    repack_history: data.repack_history || [],
                }));
            } catch (e) {
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ total: 0, changes: [], handling_changes: 0, texture_changes: 0, original_rpf: foundRpf, original_rpf_exists: !!foundRpf }));
            }
        } else {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ total: 0, changes: [], handling_changes: 0, texture_changes: 0, original_rpf: foundRpf, original_rpf_exists: !!foundRpf }));
        }
        return;
    }


    // POST /api/import-files - import modified files back into the pipeline
    if (pathname === "/api/import-files" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName, sourcePaths } = JSON.parse(body);
                if (!safeName || safeName.includes("..") || !sourcePaths?.length) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Missing safeName or sourcePaths" }));
                    return;
                }

                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                if (!fs.existsSync(previewDir)) {
                    res.writeHead(404, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Preview directory not found" }));
                    return;
                }

                const imported = [];
                const errors = [];

                for (const srcPath of sourcePaths) {
                    if (!fs.existsSync(srcPath)) {
                        errors.push(`File not found: ${srcPath}`);
                        continue;
                    }
                    const fileName = path.basename(srcPath);
                    const ext = path.extname(fileName).toLowerCase();

                    let destSubDir = "imported";
                    if ([".dds", ".png", ".tga", ".jpg"].includes(ext)) destSubDir = "imported/textures";
                    else if ([".glb", ".gltf", ".obj", ".fbx"].includes(ext)) destSubDir = "imported/models";
                    else if ([".ytd"].includes(ext)) destSubDir = "imported/ytd";
                    else if ([".meta", ".xml"].includes(ext)) destSubDir = "imported/meta";

                    const destDir = path.join(previewDir, destSubDir);
                    if (!fs.existsSync(destDir)) fs.mkdirSync(destDir, { recursive: true });
                    const destPath = path.join(destDir, fileName);

                    fs.copyFileSync(srcPath, destPath);
                    imported.push({ name: fileName, ext, dest: `${destSubDir}/${fileName}`, size: fs.statSync(destPath).size });
                    console.log(`[Import] ${fileName} -> ${destSubDir}/`);
                }

                // Record in changes.json
                if (imported.length > 0) {
                    const changesPath = path.join(previewDir, "changes.json");
                    let changesData = { safe_name: safeName, changes: [], repack_history: [] };
                    if (fs.existsSync(changesPath)) {
                        try { changesData = JSON.parse(fs.readFileSync(changesPath, "utf8")); } catch (e) {}
                    }

                    for (const imp of imported) {
                        // Remove existing change for same file
                        changesData.changes = (changesData.changes || []).filter(
                            c => !(c.type === "imported" && c.file_name === imp.name)
                        );
                        changesData.changes.push({
                            type: "imported",
                            file_name: imp.name,
                            file_ext: imp.ext,
                            modified_file: imp.dest,
                            size: imp.size,
                            timestamp: new Date().toISOString(),
                            description: `Imported modified file: ${imp.name}`,
                        });
                    }
                    changesData.last_modified = new Date().toISOString();

                    // Ensure original_rpf is set
                    const manifestP = path.join(previewDir, "manifest.json");
                    if (!changesData.original_rpf && fs.existsSync(manifestP)) {
                        try {
                            const man = JSON.parse(fs.readFileSync(manifestP, "utf8"));
                            if (man.rpf_source && fs.existsSync(man.rpf_source)) {
                                changesData.original_rpf = man.rpf_source;
                            }
                        } catch (e) {}
                    }

                    fs.writeFileSync(changesPath, JSON.stringify(changesData, null, 2));
                }

                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ imported: imported.length, errors, files: imported }));
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // GET /api/workspace?safeName=xxx - get the workspace folder path for drag-drop import
    if (pathname === "/api/workspace" && req.method === "GET") {
        const safeName = parsedUrl.query.safeName;
        if (!safeName || safeName.includes("..")) {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "Invalid name" }));
            return;
        }
        const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
        const importDir = path.join(previewDir, "imported");
        if (!fs.existsSync(importDir)) fs.mkdirSync(importDir, { recursive: true });

        // List already imported files
        const importedFiles = [];
        const walkDir = (dir, prefix) => {
            if (!fs.existsSync(dir)) return;
            for (const f of fs.readdirSync(dir)) {
                const fp = path.join(dir, f);
                const stat = fs.statSync(fp);
                if (stat.isDirectory()) walkDir(fp, `${prefix}${f}/`);
                else importedFiles.push({ name: f, path: `${prefix}${f}`, size: stat.size, modified: stat.mtime });
            }
        };
        walkDir(importDir, "imported/");

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
            preview_dir: previewDir,
            import_dir: importDir,
            imported_files: importedFiles,
        }));
        return;
    }

    // POST /api/pipeline/repack - repack modified vehicle into dlc.rpf
    if (pathname === "/api/pipeline/repack" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName } = JSON.parse(body);
                if (!safeName || safeName.includes("..")) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid name" }));
                    return;
                }
                const previewDir = path.join(ROOT_DIR, "downloads", "_previews", safeName);
                if (!fs.existsSync(previewDir)) {
                    res.writeHead(404, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Preview not found. Extract first." }));
                    return;
                }

                const pythonCmd = process.platform === "win32" ? "python" : "python3";
                const scriptPath = path.join(ROOT_DIR, "processor", "rpf_repacker.py");

                console.log(`[Pipeline] Repacking: ${safeName}`);

                execFile(pythonCmd, [scriptPath, previewDir], {
                    cwd: ROOT_DIR, timeout: 300000, maxBuffer: 10 * 1024 * 1024
                }, (err, stdout, stderr) => {
                    if (err) {
                        console.log(`[Pipeline] Repack error: ${err.message}`);
                        if (stderr) console.log(`[Pipeline] stderr: ${stderr.slice(-500)}`);
                        res.writeHead(500, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ error: err.message, details: stderr ? stderr.slice(-300) : "" }));
                        return;
                    }
                    try {
                        const result = JSON.parse(stdout.trim());
                        console.log(`[Pipeline] Repack complete: ${result.changes_applied}/${result.changes_total} applied`);
                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify(result));
                    } catch (e) {
                        console.log(`[Pipeline] Repack output: ${stdout.slice(-500)}`);
                        res.writeHead(200, { "Content-Type": "application/json" });
                        res.end(JSON.stringify({ message: "Repack complete", stdout: stdout.slice(-500) }));
                    }
                });
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // POST /api/pipeline/extract - extract a single asset
    if (pathname === "/api/pipeline/extract" && req.method === "POST") {
        let body = "";
        req.on("data", chunk => { body += chunk; });
        req.on("end", () => {
            try {
                const { safeName } = JSON.parse(body);
                if (!safeName || safeName.includes("..")) {
                    res.writeHead(400, { "Content-Type": "application/json" });
                    res.end(JSON.stringify({ error: "Invalid name" }));
                    return;
                }
                const pythonCmd = process.platform === "win32" ? "python" : "python3";
                const scriptPath = path.join(ROOT_DIR, "processor", "extract_preview.py");

                console.log(`[Pipeline] Extracting: ${safeName}`);

                execFile(pythonCmd, [scriptPath, "--asset-id", safeName], {
                    cwd: ROOT_DIR, timeout: 300000
                }, (err, stdout, stderr) => {
                    if (err) {
                        console.log(`[Pipeline] Extract error for ${safeName}: ${err.message}`);
                    } else {
                        console.log(`[Pipeline] Extracted: ${safeName}`);
                    }
                });

                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ message: `Extracting ${safeName}...` }));
            } catch (e) {
                res.writeHead(500, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ error: e.message }));
            }
        });
        return;
    }

    // Serve thumbnail/download files
    if (pathname.startsWith("/file/")) {
        const relativePath = decodeURIComponent(pathname.slice(6));
        const filePath = path.join(ROOT_DIR, relativePath);
        // Security: prevent path traversal
        if (!path.resolve(filePath).startsWith(path.resolve(ROOT_DIR))) {
            res.writeHead(403);
            res.end("Forbidden");
            return;
        }
        serveFile(res, filePath);
        return;
    }

    // Serve the dashboard HTML
    if (pathname === "/" || pathname === "/index.html") {
        serveFile(res, path.join(__dirname, "index.html"));
        return;
    }

    // Serve static files from preview dir
    const staticPath = path.join(__dirname, pathname);
    if (fs.existsSync(staticPath) && fs.statSync(staticPath).isFile()) {
        serveFile(res, staticPath);
        return;
    }

    res.writeHead(404);
    res.end("Not found");
});

server.listen(PORT, HOST, () => {
    console.log(`\n  ┌──────────────────────────────────────────────┐`);
    console.log(`  │  Asset Preview Dashboard                     │`);
    console.log(`  │  http://${HOST}:${PORT}                      │`);
    console.log(`  │  Press Ctrl+C to stop                        │`);
    console.log(`  └──────────────────────────────────────────────┘\n`);
});
