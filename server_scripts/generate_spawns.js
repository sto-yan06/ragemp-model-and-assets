/**
 * Auto Spawn Script Generator
 * 
 * Scans client_packages stream folders and generates RageMP server-side
 * spawn scripts for all assets (vehicles, weapons, objects, houses).
 */

const fs = require("fs-extra");
const path = require("path");

const CONFIG_PATH = path.join(__dirname, "..", "config.json");
const OUTPUT_DIR = path.join(__dirname, "..", "packages");

function loadConfig() {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
}

function log(msg) {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] ${msg}`);
}

/**
 * Generate vehicle spawn commands
 */
function generateVehicleSpawns(streamDir) {
    if (!fs.existsSync(streamDir)) return "";

    const files = fs.readdirSync(streamDir).filter(f => f.endsWith(".yft"));
    if (files.length === 0) return "";

    let script = `// ── Vehicle Spawns ──
// Auto-generated: ${new Date().toISOString()}
// Total vehicles: ${files.length}

const vehicleNames = [
${files.map(f => `    "${path.parse(f).name}"`).join(",\n")}
];

// Spawn all vehicles in a grid pattern for testing
mp.events.add("playerCommand", (player, command, ...args) => {
    if (command === "spawnvehicles") {
        const startPos = player.position;
        let col = 0;
        let row = 0;
        const spacing = 5.0;

        vehicleNames.forEach((name, i) => {
            const x = startPos.x + (col * spacing);
            const y = startPos.y + (row * spacing);
            const z = startPos.z;

            try {
                mp.vehicles.new(mp.joaat(name), new mp.Vector3(x, y, z), {
                    heading: 0,
                    locked: false,
                    engine: false,
                    dimension: player.dimension
                });
            } catch (e) {
                console.log(\`Failed to spawn vehicle: \${name} - \${e.message}\`);
            }

            col++;
            if (col >= 10) {
                col = 0;
                row++;
            }
        });

        player.outputChatBox(\`Spawned \${vehicleNames.length} vehicles\`);
    }

    // Spawn a specific vehicle
    if (command === "veh" && args[0]) {
        const name = args[0];
        if (vehicleNames.includes(name)) {
            const pos = player.position;
            const heading = player.heading;
            mp.vehicles.new(mp.joaat(name), new mp.Vector3(pos.x + 3, pos.y, pos.z), {
                heading: heading,
                locked: false,
                engine: false,
                dimension: player.dimension
            });
            player.outputChatBox(\`Spawned: \${name}\`);
        } else {
            player.outputChatBox(\`Vehicle not found: \${name}\`);
        }
    }

    // List all custom vehicles
    if (command === "vehicles") {
        player.outputChatBox(\`Custom vehicles (\${vehicleNames.length}):\`);
        vehicleNames.forEach(name => {
            player.outputChatBox(\`  - \${name}\`);
        });
    }
});

module.exports = { vehicleNames };
`;

    return script;
}

/**
 * Generate weapon spawn commands
 */
function generateWeaponSpawns(streamDir) {
    if (!fs.existsSync(streamDir)) return "";

    const files = fs.readdirSync(streamDir).filter(f => f.endsWith(".ydr"));
    if (files.length === 0) return "";

    let script = `// ── Weapon Spawns ──
// Auto-generated: ${new Date().toISOString()}
// Total weapons: ${files.length}

const weaponNames = [
${files.map(f => `    "${path.parse(f).name}"`).join(",\n")}
];

mp.events.add("playerCommand", (player, command, ...args) => {
    if (command === "giveweapons") {
        weaponNames.forEach(name => {
            try {
                player.giveWeapon(mp.joaat(name), 500);
            } catch (e) {
                console.log(\`Failed to give weapon: \${name}\`);
            }
        });
        player.outputChatBox(\`Given \${weaponNames.length} custom weapons\`);
    }

    if (command === "weapon" && args[0]) {
        const name = args[0];
        try {
            player.giveWeapon(mp.joaat(name), 500);
            player.outputChatBox(\`Given weapon: \${name}\`);
        } catch (e) {
            player.outputChatBox(\`Weapon not found: \${name}\`);
        }
    }

    if (command === "weapons") {
        player.outputChatBox(\`Custom weapons (\${weaponNames.length}):\`);
        weaponNames.forEach(name => {
            player.outputChatBox(\`  - \${name}\`);
        });
    }
});

module.exports = { weaponNames };
`;

    return script;
}

/**
 * Generate clothing management commands
 */
function generateClothingSpawns(streamDir) {
    if (!fs.existsSync(streamDir)) return "";

    const files = fs.readdirSync(streamDir).filter(f => f.endsWith(".ydd"));
    if (files.length === 0) return "";

    let script = `// ── Clothing Management ──
// Auto-generated: ${new Date().toISOString()}
// Total clothing items: ${files.length}

const clothingItems = [
${files.map(f => `    "${path.parse(f).name}"`).join(",\n")}
];

mp.events.add("playerCommand", (player, command, ...args) => {
    if (command === "clothes") {
        player.outputChatBox(\`Custom clothing items (\${clothingItems.length}):\`);
        clothingItems.forEach((item, i) => {
            player.outputChatBox(\`  [\${i}] \${item}\`);
        });
    }
});

module.exports = { clothingItems };
`;

    return script;
}

/**
 * Generate a master index that registers all resources
 */
function generateMasterIndex(config) {
    const targetDir = config.resource_builder.target_dir;
    const categories = config.resource_builder.categories;

    let imports = [];
    let registrations = [];

    for (const category of categories) {
        const streamDir = path.join(targetDir, category, "stream");
        if (fs.existsSync(streamDir) && fs.readdirSync(streamDir).length > 0) {
            imports.push(`const ${category}Module = require("./${category}_spawns");`);
            registrations.push(`    ${category}: ${category}Module`);
        }
    }

    return `// ── Master Asset Index ──
// Auto-generated: ${new Date().toISOString()}
// Register all custom asset modules

${imports.join("\n")}

const assetRegistry = {
${registrations.join(",\n")}
};

mp.events.add("playerReady", (player) => {
    let totalAssets = 0;
    for (const [category, mod] of Object.entries(assetRegistry)) {
        const count = Object.values(mod).filter(v => Array.isArray(v)).reduce((a, b) => a + b.length, 0);
        totalAssets += count;
    }
    player.outputChatBox(\`Server loaded \${totalAssets} custom assets.\`);
    player.outputChatBox("Type /vehicles, /weapons, or /clothes to see available items.");
});

module.exports = assetRegistry;
`;
}

// ── Main ──

function main() {
    const config = loadConfig();
    const targetDir = config.resource_builder.target_dir;

    log("=".repeat(60));
    log("Spawn Script Generator - Starting");
    log("=".repeat(60));

    fs.ensureDirSync(OUTPUT_DIR);

    // Generate vehicle spawns
    const vehicleStream = path.join(targetDir, "vehicles", "stream");
    const vehicleScript = generateVehicleSpawns(vehicleStream);
    if (vehicleScript) {
        fs.writeFileSync(path.join(OUTPUT_DIR, "vehicles_spawns.js"), vehicleScript);
        log("Generated: vehicles_spawns.js");
    }

    // Generate weapon spawns
    const weaponStream = path.join(targetDir, "weapons", "stream");
    const weaponScript = generateWeaponSpawns(weaponStream);
    if (weaponScript) {
        fs.writeFileSync(path.join(OUTPUT_DIR, "weapons_spawns.js"), weaponScript);
        log("Generated: weapons_spawns.js");
    }

    // Generate clothing spawns
    const clothesStream = path.join(targetDir, "clothes", "stream");
    const clothesScript = generateClothingSpawns(clothesStream);
    if (clothesScript) {
        fs.writeFileSync(path.join(OUTPUT_DIR, "clothes_spawns.js"), clothesScript);
        log("Generated: clothes_spawns.js");
    }

    // Generate master index
    const masterScript = generateMasterIndex(config);
    fs.writeFileSync(path.join(OUTPUT_DIR, "index.js"), masterScript);
    log("Generated: index.js (master asset registry)");

    log("\nSpawn script generation complete.");
}

main();
