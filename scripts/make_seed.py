#!/usr/bin/env python3
"""Maintainer tool: pack a small, self-consistent sample of the dataset into seed tarballs that
stand in for the S3 buckets until AWS exists. Upload them as assets of a GitHub release of this repo
(scripts/seed.py downloads them).

    python scripts/make_seed.py --data data --out dist --matches <match_key> [<match_key> ...]

Produces
    cs2wp-seed-<tag>.tar.gz      parsed/ features/ scores/ kalshi/ catalog/ models/ (for the chosen matches)
    cs2wp-seed-raw-<tag>.tar.gz  raw/<one demo>.dem  (optional: exercises upload -> parse end to end)
Stdlib only.
"""

import argparse
import json
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path


def match_key(demo_id: str) -> str:
    return demo_id.rsplit("-", 1)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", default="dist", type=Path)
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--matches", nargs="+", required=True)
    ap.add_argument("--raw-demo", help="demo id whose raw .dem goes into the optional raw tarball")
    a = ap.parse_args()
    data, out = a.data.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(data / "app.db")
    con.row_factory = sqlite3.Row
    demos = [dict(r) for r in con.execute("SELECT * FROM demos ORDER BY created_at")
             if match_key(r["id"]) in a.matches]
    ids = [d["id"] for d in demos]
    missing = set(a.matches) - {match_key(i) for i in ids}
    if missing:
        raise SystemExit(f"unknown matches: {missing}")

    reg = json.loads((data / "models/registry.json").read_text())
    v = reg["active"]
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)

        def put(rel: str):
            src = data / rel
            if src.exists():
                (t / rel).parent.mkdir(parents=True, exist_ok=True)
                (shutil.copytree if src.is_dir() else shutil.copy2)(src, t / rel)

        for d in ids:
            put(f"parsed/{d}")
            for rel in (f"features/{d}.parquet", f"scores/{d}.parquet", f"scores/{d}_events.parquet",
                        f"scores/{d}_wpa.json", f"kalshi/{d}.json", f"kalshi/{d}_candles.parquet",
                        f"kalshi/{d}_trades.parquet"):
                put(rel)
        for f in (data / "models" / v).iterdir():
            if f.is_file():
                put(f"models/{v}/{f.name}")
        for m in a.matches:
            put(f"models/{v}/cv/{m}")
        (t / "models/registry.json").write_text(json.dumps(
            {"active": v, "versions": {v: reg["versions"][v]}}, indent=1))
        (t / "catalog").mkdir()
        (t / "catalog/demos.json").write_text(json.dumps(demos, indent=0))
        for junk in t.rglob("*.etag"):
            junk.unlink()

        name = out / f"cs2wp-seed-{a.tag}.tar.gz"
        with tarfile.open(name, "w:gz") as tar:
            for p in sorted(t.iterdir()):
                tar.add(p, arcname=p.name)
        print(f"{name}  ({name.stat().st_size / 1e6:.0f} MB, {len(ids)} maps, model {v})")

    if a.raw_demo:
        name = out / f"cs2wp-seed-raw-{a.tag}.tar.gz"
        with tarfile.open(name, "w:gz") as tar:
            tar.add(data / "raw" / f"{a.raw_demo}.dem", arcname=f"raw/{a.raw_demo}.dem")
        print(f"{name}  ({name.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
