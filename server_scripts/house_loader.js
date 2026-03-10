/**
 * House / MLO Loader for RageMP
 * 
 * Manages custom interior (MLO) loading for houses.
 * Scans stream folder for .ymap/.ytyp files and generates
 * client-side loading events.
 */

const fs = require("fs-extra");
const path = require("path");

const CONFIG_PATH = path.join(__dirname, "..", "config.json");

function loadConfig() {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
}

function log(msg) {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] ${msg}`);
}

/**
 * Discover all house/MLO assets in the stream folder
 */
function discoverHouseAssets(streamDir) {
    if (!fs.existsSync(streamDir)) return { ymaps: [], ytyps: [] };

    const files = fs.readdirSync(streamDir);
    return {
        ymaps: files.filter(f => f.endsWith(".ymap")),
        ytyps: files.filter(f => f.endsWith(".ytyp")),
    };
}

/**
 * Generate house definitions with default positions
 * In production, these positions would come from CodeWalker placement data
 */
function generateHouseDefinitions(assets) {
    const houses = [];
    const processedNames = new Set();

    for (const ymap of assets.ymaps) {
        const baseName = path.parse(ymap).name;
        if (processedNames.has(baseName)) continue;
        processedNames.add(baseName);

        const hasYtyp = assets.ytyps.some(
            f => path.parse(f).name === baseName
        );

        houses.push({
            name: baseName,
            ymap: ymap,
            ytyp: hasYtyp ? `${baseName}.ytyp` : null,
            // Default position - should be configured per house
            position: { x: 0, y: 0, z: 72 },
            interior_id: null,
            price: 0,
            label: baseName.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
        });
    }

    return houses;
}

/**
 * Generate the server-side house management script
 */
function generateHouseServerScript(houses) {
    return `// ── House Management Server Script ──
// Auto-generated: ${new Date().toISOString()}
// Total houses: ${houses.length}

const houses = ${JSON.stringify(houses, null, 4)};

// Player house data (in production, use a database)
const playerHouses = new Map();

mp.events.add("playerReady", (player) => {
    // Load house interiors for the player
    player.call("loadHouses", [JSON.stringify(houses)]);
});

mp.events.add("playerCommand", (player, command, ...args) => {
    // List available houses
    if (command === "houses") {
        player.outputChatBox(\`Available houses (\${houses.length}):\`);
        houses.forEach((house, i) => {
            player.outputChatBox(\`  [\${i}] \${house.label} - $\${house.price}\`);
        });
    }

    // Teleport to a house
    if (command === "gohouse" && args[0] !== undefined) {
        const index = parseInt(args[0]);
        if (index >= 0 && index < houses.length) {
            const house = houses[index];
            player.position = new mp.Vector3(house.position.x, house.position.y, house.position.z);
            player.outputChatBox(\`Teleported to: \${house.label}\`);
        } else {
            player.outputChatBox("Invalid house index. Use /houses to see available.");
        }
    }

    // Buy a house (basic implementation)
    if (command === "buyhouse" && args[0] !== undefined) {
        const index = parseInt(args[0]);
        if (index >= 0 && index < houses.length) {
            const house = houses[index];
            playerHouses.set(player.name, {
                houseIndex: index,
                houseName: house.name,
                purchasedAt: new Date().toISOString()
            });
            player.outputChatBox(\`You purchased: \${house.label}\`);
        }
    }
});

module.exports = { houses };
`;
}

/**
 * Generate the client-side house loading script
 */
function generateHouseClientScript(houses) {
    return `// ── House Loading Client Script ──
// Auto-generated: ${new Date().toISOString()}
// Handles loading custom house interiors (MLOs)

mp.events.add("loadHouses", (housesJson) => {
    const houses = JSON.parse(housesJson);

    houses.forEach(house => {
        // Request streaming of the house model
        // The .ymap and .ytyp files in the stream folder are auto-loaded by RageMP
        mp.console.logInfo(\`House loaded: \${house.label}\`);
    });

    mp.console.logInfo(\`Total houses loaded: \${houses.length}\`);
});

// Handle entering a house interior
mp.events.add("enterHouse", (houseIndex) => {
    mp.console.logInfo(\`Entering house: \${houseIndex}\`);
    // Interior loading is handled by the streamed .ymap/.ytyp files
});
`;
}

// ── Main ──

function main() {
    const config = loadConfig();
    const targetDir = config.resource_builder.target_dir;
    const streamDir = path.join(targetDir, "houses", "stream");

    log("=".repeat(60));
    log("House/MLO Loader Generator - Starting");
    log("=".repeat(60));

    // Discover house assets
    const assets = discoverHouseAssets(streamDir);
    log(`Found ${assets.ymaps.length} .ymap files and ${assets.ytyps.length} .ytyp files`);

    // Generate house definitions
    const houses = generateHouseDefinitions(assets);
    log(`Generated ${houses.length} house definitions`);

    // Write house config
    const housesConfigPath = path.join(targetDir, "houses", "houses_config.json");
    fs.ensureDirSync(path.dirname(housesConfigPath));
    fs.writeFileSync(housesConfigPath, JSON.stringify(houses, null, 2));
    log(`House config written to: ${housesConfigPath}`);

    // Generate server script
    const packagesDir = path.join(__dirname, "..", "packages");
    fs.ensureDirSync(packagesDir);

    const serverScript = generateHouseServerScript(houses);
    fs.writeFileSync(path.join(packagesDir, "houses_server.js"), serverScript);
    log("Generated: houses_server.js");

    // Generate client script
    const clientPackagesDir = path.join(targetDir, "houses");
    const clientScript = generateHouseClientScript(houses);
    fs.writeFileSync(path.join(clientPackagesDir, "houses_client.js"), clientScript);
    log("Generated: houses_client.js");

    log("\nHouse loader generation complete.");
}

main();
