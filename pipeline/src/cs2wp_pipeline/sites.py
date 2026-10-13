"""Rebuild bomb-site centres from plant positions in the parsed demos.

The result belongs in core (``core/src/cs2wp_core/sites.json``): commit it there so training,
batch scoring and live inference keep identical coordinates.
"""

import json
from pathlib import Path

import pandas as pd

from cs2wp_core.config import PARSED
from cs2wp_core.sites import load


def rebuild() -> dict:
    plants = []
    for d in PARSED.iterdir():
        mp, ep, tp = d / "meta.json", d / "events.parquet", d / "ticks.parquet"
        if not (mp.exists() and ep.exists()):
            continue
        m = json.loads(mp.read_text())
        e = pd.read_parquet(ep)
        e = e[e["type"] == "plant"]
        if e.empty:
            continue
        t = pd.read_parquet(tp, columns=["tick", "steamid", "last_place_name"])
        for pl in e.itertuples():
            near = t[(t["steamid"] == pl.actor_steamid) & (t["tick"] <= pl.tick)].tail(1)
            place = (near["last_place_name"].iloc[0] if len(near) else "") or ""
            label = "A" if place.endswith("A") else "B" if place.endswith("B") else None
            if label:
                plants.append({"map": m["map"], "site": label, "x": pl.x, "y": pl.y})
    df = pd.DataFrame(plants)
    out = load()
    if not df.empty:
        for (mp, site), g in df.groupby(["map", "site"]):
            out.setdefault(mp, {})[site] = [round(float(g["x"].median()), 1), round(float(g["y"].median()), 1),
                                            int(len(g))]
    return out


def write(out: dict, path: Path) -> None:
    path.write_text(json.dumps(out, indent=1, sort_keys=True))
