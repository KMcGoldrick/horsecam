"""App settings, stored as JSON in %APPDATA%\\HorseCam\\settings.json."""
import json
import os

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "HorseCam")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
MODELS_DIR = os.path.join(APP_DIR, "models")

DEFAULTS = {
    "library": "",                       # root folder on the hard drive
    "cameras": ["Cam1", "Cam2", "Cam3", "Cam4", "Cam5", "Cam6"],
    "model": "yolo11m.pt",               # n/s = faster, l/x = more accurate
    "imgsz": 960,                        # larger helps with small/distant horses
    "device": "",                        # "" = auto, "cpu", or "0" for first GPU
    "batch": 8,
    "horse_conf": 0.40,                  # at/above -> horse
    "review_conf": 0.15,                 # between review and horse -> review folder
    "visit_gap_min": 10,                 # photos closer than this = same visit
    "last_camera": "",
    "text_size": 1.3,                    # text scale: 1.0 = original size
    "theme": "Meadow",                   # color theme (see theme.py)
}


def load():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save(s):
    os.makedirs(APP_DIR, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SETTINGS_PATH)
