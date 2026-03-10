/**
 * Pipeline Orchestrator
 * 
 * Runs the full asset pipeline in sequence:
 * 1. Scrape free assets
 * 2. Extract & sort downloads
 * 3. Generate AI textures (if enabled)
 * 4. Process models via Blender (if available)
 * 5. Convert to GTA formats
 * 6. Build RageMP stream resources
 * 7. Generate spawn scripts
 * 8. Generate house loaders
 * 
 * Can be run manually or via scheduler.
 */

const { execSync, spawn } = require("child_process");
const fs = require("fs-extra");
const path = require("path");

const CONFIG_PATH = path.join(__dirname, "config.json");
const LOG_DIR = path.join(__dirname, "logs");

function loadConfig() {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
}

function log(msg, level = "INFO") {
    const timestamp = new Date().toISOString();
    const line = `[${timestamp}] [${level}] ${msg}`;
    console.log(line);

    // Also write to log file
    fs.ensureDirSync(LOG_DIR);
    const logFile = path.join(LOG_DIR, `pipeline_${new Date().toISOString().split("T")[0]}.log`);
    fs.appendFileSync(logFile, line + "\n");
}

/**
 * Run a Python script and capture output
 */
function runPython(scriptPath, description) {
    log(`Starting: ${description}`);
    const startTime = Date.now();

    try {
        const result = execSync(`python "${scriptPath}"`, {
            cwd: __dirname,
            timeout: 30 * 60 * 1000, // 30 min timeout
            encoding: "utf8",
            stdio: ["pipe", "pipe", "pipe"],
        });

        const elapsed = Math.round((Date.now() - startTime) / 1000);
        log(`Completed: ${description} (${elapsed}s)`);
        return { success: true, output: result, elapsed };
    } catch (e) {
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        log(`FAILED: ${description} (${elapsed}s) - ${e.message}`, "ERROR");
        return { success: false, error: e.message, elapsed };
    }
}

/**
 * Run a Node.js script
 */
function runNode(scriptPath, description) {
    log(`Starting: ${description}`);
    const startTime = Date.now();

    try {
        const result = execSync(`node "${scriptPath}"`, {
            cwd: __dirname,
            timeout: 10 * 60 * 1000, // 10 min timeout
            encoding: "utf8",
            stdio: ["pipe", "pipe", "pipe"],
        });

        const elapsed = Math.round((Date.now() - startTime) / 1000);
        log(`Completed: ${description} (${elapsed}s)`);
        return { success: true, output: result, elapsed };
    } catch (e) {
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        log(`FAILED: ${description} (${elapsed}s) - ${e.message}`, "ERROR");
        return { success: false, error: e.message, elapsed };
    }
}

/**
 * Run Blender processing (if Blender is available)
 */
function runBlender(config) {
    const blenderExe = config.blender.executable;
    const scriptPath = path.join(__dirname, config.blender.scripts_dir, "batch_process.py");
    const inputDir = path.join(__dirname, config.blender.input_dir);
    const outputDir = path.join(__dirname, config.blender.output_dir);

    if (!fs.existsSync(scriptPath)) {
        log("Blender script not found, skipping model processing", "WARN");
        return { success: false, skipped: true };
    }

    if (!fs.existsSync(inputDir) || fs.readdirSync(inputDir).length === 0) {
        log("No raw models to process, skipping Blender step", "WARN");
        return { success: false, skipped: true };
    }

    log("Starting: Blender model processing");
    const startTime = Date.now();

    try {
        const cmd = `"${blenderExe}" --background --python "${scriptPath}" -- --input "${inputDir}" --output "${outputDir}"`;
        const result = execSync(cmd, {
            cwd: __dirname,
            timeout: 60 * 60 * 1000, // 60 min timeout
            encoding: "utf8",
            stdio: ["pipe", "pipe", "pipe"],
        });

        const elapsed = Math.round((Date.now() - startTime) / 1000);
        log(`Completed: Blender processing (${elapsed}s)`);
        return { success: true, output: result, elapsed };
    } catch (e) {
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        log(`Blender processing failed (${elapsed}s): ${e.message}`, "WARN");
        return { success: false, error: e.message, elapsed };
    }
}

/**
 * Restart the RageMP server (if configured)
 */
function restartServer(config) {
    if (!config.server.auto_restart) {
        log("Server auto-restart is disabled");
        return { success: false, skipped: true };
    }

    const restartCmd = config.server.restart_command;
    if (!restartCmd) {
        log("No restart command configured", "WARN");
        return { success: false, skipped: true };
    }

    log("Restarting RageMP server...");
    try {
        execSync(restartCmd, { timeout: 60000, encoding: "utf8" });
        log("Server restarted successfully");
        return { success: true };
    } catch (e) {
        log(`Server restart failed: ${e.message}`, "ERROR");
        return { success: false, error: e.message };
    }
}

// ── Pipeline Steps ──

const PIPELINE_STEPS = [
    {
        name: "Scrape Assets",
        run: () => runPython(
            path.join(__dirname, "scraper", "scrape_assets.py"),
            "Asset scraping (free content only)"
        ),
    },
    {
        name: "Extract & Sort",
        run: () => runPython(
            path.join(__dirname, "processor", "extract_assets.py"),
            "Asset extraction and sorting"
        ),
    },
    {
        name: "AI Texture Generation",
        run: (config) => {
            if (!config.ai_textures.enabled) {
                log("AI textures disabled, skipping", "WARN");
                return { success: false, skipped: true };
            }
            return runPython(
                path.join(__dirname, "ai_textures", "generate_textures.py"),
                "AI texture generation"
            );
        },
    },
    {
        name: "AI Variations",
        run: (config) => {
            if (!config.ai_textures.enabled) {
                log("AI variations disabled, skipping", "WARN");
                return { success: false, skipped: true };
            }
            return runPython(
                path.join(__dirname, "ai_textures", "variation_generator.py"),
                "AI variation generation"
            );
        },
    },
    {
        name: "Blender Processing",
        run: (config) => runBlender(config),
    },
    {
        name: "GTA Conversion",
        run: () => runPython(
            path.join(__dirname, "gta_converter", "convert_assets.py"),
            "GTA format conversion"
        ),
    },
    {
        name: "Build Resources",
        run: () => runNode(
            path.join(__dirname, "resource_builder", "build_resources.js"),
            "RageMP resource building"
        ),
    },
    {
        name: "Generate Spawns",
        run: () => runNode(
            path.join(__dirname, "server_scripts", "generate_spawns.js"),
            "Spawn script generation"
        ),
    },
    {
        name: "Generate Houses",
        run: () => runNode(
            path.join(__dirname, "server_scripts", "house_loader.js"),
            "House loader generation"
        ),
    },
    {
        name: "Restart Server",
        run: (config) => restartServer(config),
    },
];

// ── Main ──

function main() {
    const config = loadConfig();
    const startTime = Date.now();

    log("╔══════════════════════════════════════════════════════╗");
    log("║     RageMP Asset Pipeline - Full Run                ║");
    log("╚══════════════════════════════════════════════════════╝");
    log(`Started at: ${new Date().toISOString()}`);

    const results = [];

    for (const step of PIPELINE_STEPS) {
        log(`\n${"─".repeat(50)}`);
        log(`Step: ${step.name}`);
        log("─".repeat(50));

        const result = step.run(config);
        results.push({ step: step.name, ...result });

        if (!result.success && !result.skipped) {
            log(`Step "${step.name}" failed, but continuing pipeline...`, "WARN");
        }
    }

    // ── Summary ──

    const totalElapsed = Math.round((Date.now() - startTime) / 1000);

    log("\n" + "═".repeat(50));
    log("PIPELINE SUMMARY");
    log("═".repeat(50));

    for (const r of results) {
        const status = r.skipped ? "SKIPPED" : r.success ? "OK" : "FAILED";
        const time = r.elapsed ? ` (${r.elapsed}s)` : "";
        log(`  [${status}] ${r.step}${time}`);
    }

    const succeeded = results.filter(r => r.success).length;
    const failed = results.filter(r => !r.success && !r.skipped).length;
    const skipped = results.filter(r => r.skipped).length;

    log(`\nTotal: ${succeeded} succeeded, ${failed} failed, ${skipped} skipped`);
    log(`Total time: ${totalElapsed}s`);

    // Write pipeline report
    const report = {
        timestamp: new Date().toISOString(),
        total_seconds: totalElapsed,
        results: results,
        summary: { succeeded, failed, skipped },
    };

    const reportPath = path.join(LOG_DIR, `pipeline_report_${new Date().toISOString().split("T")[0]}.json`);
    fs.ensureDirSync(LOG_DIR);
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    log(`Report saved: ${reportPath}`);
}

main();
