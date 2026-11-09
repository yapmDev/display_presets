"""The presets, the only thing the app keeps: ~/.config/display_presets/presets.json.

A preset is {"name": str, "layout": <displays.py layout>}. The list's order is
the order the window shows them in. No GTK.
"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "display_presets"
PRESETS_FILE = CONFIG_DIR / "presets.json"


def _valid(preset):
    try:
        return (isinstance(preset["name"], str) and preset["name"].strip()
                and isinstance(preset["layout"]["logical"], list))
    except (KeyError, TypeError):
        return False


def load():
    """Every saved preset. A missing or corrupt file means none yet; a single
    malformed entry is dropped rather than losing the rest."""
    try:
        data = json.loads(PRESETS_FILE.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if _valid(p)]


def save(presets):
    """Write the whole list. Written to a temporary file and renamed into
    place, so a crash mid-write cannot leave half a file behind."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PRESETS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(presets, indent=2))
    tmp.replace(PRESETS_FILE)


def find(presets, name):
    """The preset called `name`, compared without case, or None."""
    key = name.strip().casefold()
    return next((p for p in presets if p["name"].strip().casefold() == key), None)
