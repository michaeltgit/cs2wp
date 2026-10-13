#!/usr/bin/env python3
"""Download the sample dataset (the stand-in for the S3 buckets) and load it.

    python scripts/seed.py                    # lite: unpack into ./data (CS2WP_DATA) + build the SQLite catalog
    python scripts/seed.py --stack            # stack: also upload to the compose S3 + import into Postgres
    python scripts/seed.py --with-raw         # also fetch one raw .dem (to test ingest -> parse end to end)

The tarballs are assets of this repo's GitHub release ``seed-<tag>``, downloaded over HTTPS (falls
back to the GitHub CLI if the repo is private). The load steps run the cs2wp-pipeline CLI via uv.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("CS2WP_SEED_REPO", "michaeltgit/cs2wp")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # repo root (the uv workspace)


def download(tag: str, name: str, dest: Path) -> None:
    url = f"https://github.com/{REPO}/releases/download/seed-{tag}/{name}"
    print(f"downloading {url}", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(dest / name, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        sh(["gh", "release", "download", f"seed-{tag}", "-R", REPO, "-D", str(dest), "-p", name])  # private repo


def sh(cmd, env=None, cwd=None):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, env=env, cwd=cwd)


def stack_env(data: Path) -> dict:
    env = dict(os.environ)
    for line in (ROOT / ".env.example").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    env["CS2WP_DATA"] = str(data)
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--data", default=os.environ.get("CS2WP_DATA", str(ROOT / "data")))
    ap.add_argument("--stack", action="store_true", help="upload to the docker-compose S3 + Postgres")
    ap.add_argument("--with-raw", action="store_true")
    ap.add_argument("--from-dir", help="use tarballs already on disk instead of downloading")
    a = ap.parse_args()
    data = Path(a.data).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(a.from_dir) if a.from_dir else Path(tmp)
        patterns = [f"cs2wp-seed-{a.tag}.tar.gz"] + ([f"cs2wp-seed-raw-{a.tag}.tar.gz"] if a.with_raw else [])
        if not a.from_dir:
            for p in patterns:
                download(a.tag, p, src)
        for p in patterns:
            with tarfile.open(src / p) as tar:
                tar.extractall(data, filter="data")
            print(f"unpacked {p} -> {data}")

    run = ["uv", "run", "--directory", str(ROOT), "cs2wp-pipeline"]
    env = dict(os.environ, CS2WP_DATA=str(data))
    if a.stack:
        env = stack_env(data)
        sh(run + ["publish-all"] + ([] if a.with_raw else ["--skip-raw"]), env=env)
    sh(run + ["catalog-import"], env=env)
    sh(run + ["status"], env=env)
    print("\nseeded. lite: uv run cs2wp-api   stack: docker compose --profile app up -d --build")


if __name__ == "__main__":
    sys.exit(main())
