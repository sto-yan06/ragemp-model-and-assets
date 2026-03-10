# RageMP Vehicle Workshop

Web dashboard for downloading, previewing, editing handling, and repacking GTA V addon vehicles (`dlc.rpf`) for RageMP servers.

**Download → Preview → Edit Handling → Edit Textures (external) → Repack → Deploy**

---

## Quick Start

### 1. Prerequisites

Make sure you have these installed:

| Software | Required | Download |
|----------|----------|----------|
| **Node.js** 18+ | Yes | https://nodejs.org/ |
| **Python** 3.9+ | Yes | https://python.org/ |
| **Blender** 3.0+ | For 3D editing | https://blender.org/ |
| **GIMP** or **Paint.NET** | For texture editing | https://gimp.org/ or https://getpaint.net/ |
| **OpenIV** | For RPF inspection | https://openiv.com/ |
| **CodeWalker** | For asset extraction | https://codewalker.net/ |

### 2. Install

```bash
# Clone the repo
git clone <repo-url>
cd "ragemp model and assets"

# Install Node.js dependencies
npm install

# Install Python dependencies
pip install -r requirements.txt
```

Or run the setup script (Windows):
```powershell
.\setup.bat
```

### 3. Configure External Tools

Edit **`config.json`** → `external_tools` section with your actual install paths:

```json
"external_tools": {
    "blender_path": "C:/Program Files/Blender Foundation/Blender 4.0/blender.exe",
    "gimp_path": "C:/Program Files/GIMP 2/bin/gimp-2.10.exe",
    "paintnet_path": "C:/Program Files/paint.net/paintdotnet.exe",
    "openiv_path": "C:/Program Files/OpenIV/OpenIV.exe",
    "codewalker_path": "C:/Tools/CodeWalker/CodeWalker.exe"
}
```

> **Tip:** Right-click the `.exe` of each program → Properties → copy the path, then paste it in. Use forward slashes `/`.

### 4. Start the Dashboard

```bash
npm run preview
```

Then open **http://127.0.0.1:3000** in your browser.

---

## Project Structure

```
ragemp-vehicle-workshop/
├── config.json                  # Tool paths + pipeline settings
├── package.json                 # Node.js dependencies
├── requirements.txt             # Python dependencies
├── setup.bat                    # One-click Windows setup
│
├── preview/                     # Web dashboard
│   ├── server.js                # HTTP server + API endpoints
│   ├── index.html               # Dashboard UI (single-page app)
│   └── glb_processor.js         # 3D model processing (texture embedding)
│
├── processor/                   # Asset processing
│   ├── extract_preview.py       # Extract RPF contents for preview
│   ├── rpf_repacker.py          # Repack modified vehicles into dlc.rpf
│   └── change_tracker.py        # Track modifications per vehicle
│
├── gta_converter/               # GTA V format tools
│   └── rpf_parser.py            # Read/write RPF archives
│
├── scraper/                     # Vehicle scraper
│   └── scrape_assets.py         # Download addon vehicles from gta5-mods
│
├── downloads/                   # [Generated] Downloaded vehicles
│   ├── _metadata/               # Asset index
│   └── _previews/               # Extracted previews per vehicle
│
└── new_dlc_exported/            # [Generated] Repacked vehicles ready to use
    ├── Vehicle_Name_A/
    │   └── dlc.rpf              # Latest repacked RPF
    └── Vehicle_Name_B/
        └── dlc.rpf
```

---

## Workflow

### For Each Vehicle:

1. **Download** — Scrape from gta5-mods or drop a `.zip` manually into `downloads/`
2. **Extract** — Dashboard auto-extracts RPF contents (models, textures, handling)
3. **Preview** — View 3D model, screenshots, textures in the browser
4. **Edit Handling** — Use the visual handling editor (sliders + presets)
5. **Edit Textures** — Click "Open in GIMP" to remove logos, rebrand, etc.
6. **Import Back** — Go to Export tab, paste the path to your edited file, click Import
7. **Repack** — Click "Repack into DLC.RPF" to create the final file
8. **Deploy** — Find your repacked `dlc.rpf` in `new_dlc_exported/<vehicle_name>/`

### 3D Preview Controls:
- **Drag** to rotate, **scroll** to zoom
- **Flip** button cycles through orientations if the model looks upside down
- **Embed Textures** applies extracted textures to the 3D model
- **Open in Blender** for advanced editing

---

## Dashboard Tabs

| Tab | What It Does |
|-----|-------------|
| **Screenshots** | View mod screenshots from gta5-mods |
| **Contents** | Browse all files inside the archive |
| **Textures** | View/edit textures, open in GIMP/Paint.NET |
| **3D Preview** | Interactive 3D model viewer |
| **Handling** | Visual handling.meta editor with presets |
| **Export** | Import modified files, repack into dlc.rpf |

---

## Where Are My Exported Cars?

After repacking, find your ready-to-use `dlc.rpf` files in:

```
new_dlc_exported/
├── 2023_BMW_M4_CSL_Add-On_Extras/
│   └── dlc.rpf          ← drop this into your RageMP server
├── 2020_Kawasaki_Z_H2/
│   └── dlc.rpf
└── ...
```

Each vehicle gets its own subfolder. The `dlc.rpf` is always the latest repack.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Tool not found" when clicking Open in Blender/GIMP | Update paths in `config.json` → `external_tools` |
| 3D model looks upside down | Click the **Flip** button to cycle orientations |
| Textures not showing on 3D model | Click **Embed Textures** button |
| "Original dlc.rpf not found" on export | Re-extract the asset from the dashboard |
| Server won't start | Check if port 3000 is in use: `netstat -ano | findstr :3000` |

---

## Legal Notice

This tool works with **free, publicly available** addon vehicles only:
- The scraper skips premium/paid content automatically
- Rate limiting and robots.txt compliance are built-in
- Always verify licensing of downloaded assets before server deployment
