"""Bomb site centres per map (frozen in sites.json, versioned with the feature library).

Training, batch scoring and live inference must use identical coordinates, so they ship with
cs2wp-core. The pipeline's `sites rebuild` command regenerates the file from plant positions.
"""

import json
from pathlib import Path

SITES_FILE = Path(__file__).with_name("sites.json")


def load() -> dict:
    return json.loads(SITES_FILE.read_text()) if SITES_FILE.exists() else {}
