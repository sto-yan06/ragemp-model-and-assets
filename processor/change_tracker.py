"""
Change Tracker for Vehicle Asset Modifications.

Tracks all modifications made to a vehicle's files (textures, handling.meta, etc.)
relative to the original dlc.rpf. Enables repacking with a clear audit trail.

Each asset gets a changes.json in its preview directory:
{
    "safe_name": "2023_BMW_M4_CSL_Add-On_Extras",
    "original_rpf": "path/to/original/dlc.rpf",
    "original_rpf_hash": "sha256:...",
    "changes": [
        {
            "type": "handling",
            "rpf_path": "common/data/handling.meta",
            "modified_file": "handling_modified.meta",
            "timestamp": "2026-03-10T14:00:00",
            "description": "Modified top speed and acceleration"
        },
        {
            "type": "texture",
            "rpf_path": "x64/vehicles.rpf/vehiclename/vehiclename.ytd",
            "texture_name": "vehiclename_sign_1",
            "original_file": "textures/vehiclename_sign_1.png",
            "modified_file": "textures_modified/vehiclename_sign_1.png",
            "timestamp": "2026-03-10T14:05:00",
            "description": "Logo removed"
        }
    ],
    "last_modified": "2026-03-10T14:05:00",
    "repack_history": [
        {
            "timestamp": "2026-03-10T14:10:00",
            "output_path": "exports/vehiclename_dlc.rpf",
            "changes_applied": 2,
            "validation": {"status": "ok", "file_count_match": true, "structure_match": true}
        }
    ]
}
"""

import json
import hashlib
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ChangeTracker:
    """Tracks modifications to vehicle assets for repacking."""

    CHANGES_FILE = "changes.json"

    def __init__(self, preview_dir):
        """
        Args:
            preview_dir: Path to the asset's preview directory
                         (e.g. downloads/_previews/2023_BMW_M4_CSL_Add-On_Extras)
        """
        self.preview_dir = Path(preview_dir)
        self.changes_path = self.preview_dir / self.CHANGES_FILE
        self.data = self._load()

    def _load(self):
        """Load existing changes or create empty tracker."""
        if self.changes_path.exists():
            try:
                with open(self.changes_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Corrupted changes.json in {self.preview_dir}, resetting")
        return {
            "safe_name": self.preview_dir.name,
            "original_rpf": None,
            "original_rpf_hash": None,
            "changes": [],
            "last_modified": None,
            "repack_history": [],
        }

    def _save(self):
        """Persist changes to disk."""
        self.data["last_modified"] = datetime.now().isoformat()
        with open(self.changes_path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def set_original_rpf(self, rpf_path):
        """Register the original dlc.rpf path and hash."""
        rpf_path = str(rpf_path)
        self.data["original_rpf"] = rpf_path
        if os.path.exists(rpf_path):
            h = hashlib.sha256()
            with open(rpf_path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            self.data["original_rpf_hash"] = f"sha256:{h.hexdigest()}"
        self._save()

    def find_original_rpf(self, asset_entry):
        """Find the dlc.rpf path for an asset from its download or extraction info."""
        # Check if already set
        if self.data.get("original_rpf") and os.path.exists(self.data["original_rpf"]):
            return self.data["original_rpf"]

        # Look in manifest for rpf_source
        manifest_path = self.preview_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.load(open(manifest_path))
                rpf_src = manifest.get("rpf_source")
                if rpf_src and os.path.exists(rpf_src):
                    self.set_original_rpf(rpf_src)
                    return rpf_src
            except (json.JSONDecodeError, IOError):
                pass

        # Look for dlc.rpf in extracted temp directory
        safe_name = self.preview_dir.name
        possible_paths = [
            self.preview_dir / "original" / "dlc.rpf",
            self.preview_dir.parent.parent / safe_name / "dlc.rpf",
        ]
        for p in possible_paths:
            if p.exists():
                self.set_original_rpf(str(p))
                return str(p)

        return None

    def record_handling_change(self, rpf_internal_path, modified_data, description=""):
        """Record a handling.meta modification."""
        # Save modified handling file
        mod_dir = self.preview_dir / "modified"
        mod_dir.mkdir(exist_ok=True)
        mod_path = mod_dir / "handling.meta"
        with open(mod_path, 'wb') as f:
            f.write(modified_data if isinstance(modified_data, bytes) else modified_data.encode('utf-8'))

        # Remove previous handling changes (only keep latest)
        self.data["changes"] = [c for c in self.data["changes"] if c["type"] != "handling"]

        self.data["changes"].append({
            "type": "handling",
            "rpf_path": rpf_internal_path,
            "modified_file": str(mod_path.relative_to(self.preview_dir)),
            "timestamp": datetime.now().isoformat(),
            "description": description or "Handling.meta modified",
            "size": len(modified_data) if isinstance(modified_data, bytes) else len(modified_data.encode('utf-8')),
        })
        self._save()
        logger.info(f"Tracked handling change: {rpf_internal_path}")
        return str(mod_path)

    def record_texture_change(self, rpf_internal_path, texture_name,
                               original_png, modified_png, description=""):
        """Record a texture modification (logo removal, etc.)."""
        mod_dir = self.preview_dir / "textures_modified"
        mod_dir.mkdir(exist_ok=True)

        # Copy modified texture
        mod_path = mod_dir / f"{texture_name}.png"
        if isinstance(modified_png, (bytes, bytearray)):
            with open(mod_path, 'wb') as f:
                f.write(modified_png)
        else:
            shutil.copy2(modified_png, mod_path)

        # Remove previous change for same texture
        self.data["changes"] = [
            c for c in self.data["changes"]
            if not (c["type"] == "texture" and c.get("texture_name") == texture_name)
        ]

        self.data["changes"].append({
            "type": "texture",
            "rpf_path": rpf_internal_path,
            "texture_name": texture_name,
            "original_file": original_png if isinstance(original_png, str) else None,
            "modified_file": str(mod_path.relative_to(self.preview_dir)),
            "timestamp": datetime.now().isoformat(),
            "description": description or f"Texture '{texture_name}' modified",
        })
        self._save()
        logger.info(f"Tracked texture change: {texture_name}")
        return str(mod_path)

    def get_changes(self):
        """Get all recorded changes."""
        return self.data.get("changes", [])

    def get_change_summary(self):
        """Get a summary of all changes for the UI."""
        changes = self.get_changes()
        handling = [c for c in changes if c["type"] == "handling"]
        textures = [c for c in changes if c["type"] == "texture"]
        return {
            "total": len(changes),
            "handling_changes": len(handling),
            "texture_changes": len(textures),
            "changes": changes,
            "original_rpf": self.data.get("original_rpf"),
            "original_rpf_exists": bool(self.data.get("original_rpf") and
                                         os.path.exists(self.data["original_rpf"])),
            "last_modified": self.data.get("last_modified"),
            "repack_history": self.data.get("repack_history", []),
        }

    def record_repack(self, output_path, changes_applied, validation_result):
        """Record a successful repack."""
        self.data.setdefault("repack_history", []).append({
            "timestamp": datetime.now().isoformat(),
            "output_path": str(output_path),
            "changes_applied": changes_applied,
            "validation": validation_result,
        })
        self._save()

    def clear_changes(self):
        """Clear all tracked changes."""
        self.data["changes"] = []
        self._save()
