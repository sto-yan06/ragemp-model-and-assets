# RageMP Lore-Friendly Vehicle Workshop

All-in-one tool for downloading **lore-friendly** GTA V addon vehicles from [gta5-mods.com](https://www.gta5-mods.com/vehicles/tags/lore-friendly), previewing them in-browser, editing handling parameters, and repacking into `dlc.rpf` for RageMP servers.

```
Scrape → Download → Extract → Preview → Edit Handling → Repack → Deploy
```

---

## Quick Start

### Prerequisites

| Software | Version | Download |
|----------|---------|----------|
| **Node.js** | 18+ | https://nodejs.org/ |
| **Python** | 3.9+ | https://python.org/ |
| **7-Zip** | Any | https://7-zip.org/ *(for .rar/.7z archives)* |

No external tools needed (no Blender, no GIMP, no OpenIV, no CodeWalker).

### Install

**Option A — Setup script (Windows):**
```powershell
.\setup.bat
```

**Option B — Manual:**
```bash
git clone <repo-url>
cd "ragemp model and assets"

npm install
pip install -r requirements.txt
```

### Start

```bash
npm run preview
```

Open **http://127.0.0.1:3000** in your browser.

---

## How It Works

### 1. Scrape Lore-Friendly Vehicles

Click **"Scrape Lore-Friendly"** in the dashboard toolbar. Set the count (default 20, max 1500).

The scraper:
- Crawls all **66 pages** of https://www.gta5-mods.com/vehicles/tags/lore-friendly
- Filters for **Add-On** vehicles only (they have `dlc.rpf` files)
- Skips premium/paid content automatically
- Downloads archives with metadata, thumbnails, and screenshots
- Handles the gta5-mods two-step download (interstitial → CDN)

Or run from the command line:
```bash
python scraper/scrape_assets.py --category vehicles --count 50
```

### 2. Extract & Preview

Click **"Extract All"** or extract individual vehicles from their detail modal.

Extraction handles:
- ZIP, RAR, and 7z archives
- **Nested archives** (e.g. `replace.zip` inside the main download)
- RPF unpacking (textures, models, handling.meta)
- Automatic texture conversion (DDS → PNG for preview)
- 3D model conversion (YFT → GLB for in-browser preview)

### 3. Edit Handling

Open any vehicle → **Handling** tab:
- All key `handling.meta` parameters with sliders
- Categories: Performance, Braking, Traction, Suspension, Drag & Weight, Steering, Drivetrain
- **Presets**: Stock Sedan, Sports Car, Supercar, Muscle Car, Drift, SUV/Truck, Motorcycle
- Original values are loaded directly from the vehicle's `dlc.rpf`
- **Save** stores your changes, **Pack into dlc.rpf** writes them into the archive
- **Export handling.meta** downloads the XML file
- **Export RageMP JS** generates a server-side script for runtime handling override

### 4. Repack & Deploy

Open any vehicle → **Export** tab:
- See all tracked changes (handling modifications, texture edits)
- Click **"Repack into DLC.RPF"** to create the final file
- The repacker preserves the original RPF file size (critical for client compatibility)
- A backup `.rpf.bak` is created automatically before modification
- Find your repacked files in `new_dlc_exported/<vehicle_name>/dlc.rpf`

---

## Project Structure

```
ragemp-vehicle-workshop/
├── config.json              # Scraper settings, paths, pipeline config
├── package.json             # Node.js dependencies
├── requirements.txt         # Python dependencies
├── setup.bat                # One-click Windows setup
├── run.py                   # CLI pipeline runner
│
├── preview/                 # Web dashboard
│   ├── server.js            # HTTP API server
│   ├── index.html           # Single-page dashboard UI
│   └── glb_processor.js     # GLB texture embedding & rotation
│
├── processor/               # Asset processing pipeline
│   ├── extract_preview.py   # Archive extraction + RPF unpacking
│   ├── rpf_repacker.py      # Repack modified handling into dlc.rpf
│   ├── rpf_packer.py        # Low-level RPF packing
│   ├── change_tracker.py    # Track modifications per vehicle
│   └── logo_remover.py      # Auto logo removal from textures
│
├── gta_converter/           # GTA V format parsers
│   ├── rpf_parser.py        # RPF7 archive read/write
│   ├── ytd_parser.py        # YTD texture dictionary parser
│   └── yft_parser.py        # YFT model parser → OBJ/GLB
│
├── scraper/                 # Lore-friendly vehicle scraper
│   ├── scrape_assets.py     # Multi-page scraper for gta5-mods.com
│   └── download_history.json # Tracks what's been downloaded
│
├── downloads/               # [Generated] Downloaded vehicles
│   ├── vehicles/            # Raw downloaded archives
│   ├── _metadata/           # Asset index (asset_index.json)
│   └── _previews/           # Extracted previews per vehicle
│       └── <Vehicle_Name>/
│           ├── extracted/   # Unpacked archive contents
│           ├── textures/    # Converted textures (PNG)
│           ├── models/      # Converted 3D models (GLB)
│           └── original/    # Preserved original dlc.rpf
│
└── new_dlc_exported/        # [Generated] Repacked vehicles
    └── <Vehicle_Name>/
        └── dlc.rpf          # ← Drop into your RageMP server
```

---

## Dashboard Tabs

| Tab | Description |
|-----|-------------|
| **Screenshots** | View mod screenshots from gta5-mods.com |
| **Contents** | Browse all files inside the archive (with nested ZIP support) |
| **Textures** | View extracted textures; click to quick-edit with built-in canvas editor |
| **3D Preview** | Interactive 3D model viewer (rotate, zoom, flip orientation) |
| **Handling** | Visual handling.meta editor — sliders, presets, save, pack, export |
| **Export** | Change tracker, repack history, one-click RPF repack |

---

## Configuration

Edit `config.json` to adjust:

```jsonc
{
  "scraper": {
    "sources": [{
      "url": "https://www.gta5-mods.com/vehicles/tags/lore-friendly",
      "max_per_run": 1500,    // max vehicles per scrape run
      "max_pages": 66         // pages to crawl
    }],
    "delay_between_requests_seconds": 5  // be nice to the server
  },
  "preview": {
    "port": 3000              // dashboard port
  }
}
```

---

## CLI Usage

```bash
# Scrape 50 lore-friendly vehicles
python scraper/scrape_assets.py --category vehicles --count 50

# Start the dashboard
npm run preview

# Run the full pipeline (scrape + extract)
python run.py --category vehicles --count 20 --preview
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| 3D model looks upside down | Click **Flip** button to cycle orientations |
| "Original dlc.rpf not found" on Export tab | Re-extract the asset first |
| RAR files fail to extract | Install [7-Zip](https://7-zip.org/) (must be in `C:\Program Files\7-Zip\`) |
| Nested ZIPs not extracted | Re-extract — the tool now handles nested archives automatically |
| Server won't start | Check port: `netstat -ano \| findstr :3000` |
| Scraper returns no results | Check your internet connection; the site may be rate-limiting you |

---

## Legal Notice

This tool works with **free, publicly available** addon vehicles only:
- The scraper **skips premium/paid content** automatically
- Rate limiting (5s between requests) and robots.txt compliance are built-in
- Downloaded vehicles remain property of their original authors
- Always verify licensing before deploying assets to a public server
