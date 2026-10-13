"""Ingest: archives (.rar/.zip/.7z/.bz2/.gz) or .dem files -> data/raw/<demo_id>.dem, deduped by sha1."""

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from cs2wp_core import db, storage
from cs2wp_core.config import RAW

ARCHIVES = {".rar", ".zip", ".7z", ".bz2", ".gz"}


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "demo"


def _add_dem(dem: Path, original_name: str) -> str | None:
    with open(dem, "rb") as f:
        magic = f.read(8)
    if magic != b"PBDEMS2\x00":
        return None  # not a CS2 demo
    sha1 = _sha1(dem)
    existing = db.demo_by_sha1(sha1)
    if existing:
        return existing["id"]
    demo_id = f"{_slug(Path(original_name).stem)}-{sha1[:8]}"
    shutil.copyfile(dem, RAW / f"{demo_id}.dem")
    storage.publish(f"raw/{demo_id}.dem")  # demo archive (S3) keeps the original
    db.add_demo(demo_id, original_name, sha1)
    return demo_id


def _extract(path: Path, out: Path):
    """HLTV archives use the newest RAR format. RARLAB's unrar unpacks all of them (the Docker image
    has it); unar works on macOS (Homebrew) but its Linux builds fail part-way through some maps;
    7-Zip is the last resort. The first one that yields .dem files wins."""
    errors = []
    for cmd in (["unrar", "x", "-o+", "-idq", str(path), f"{out}/"],
                ["unar", "-q", "-f", "-D", "-o", str(out), str(path)],
                ["7zz", "x", "-y", f"-o{out}", str(path)]):
        if not shutil.which(cmd[0]):
            errors.append(f"{cmd[0]} not installed")
            continue
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and any(out.rglob("*.dem")):
            return
        errors.append(f"{cmd[0]}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or r.returncode}")
    raise ValueError("could not extract archive: " + "; ".join(map(str, errors)))


def ingest(path: Path) -> list[str]:
    """Returns the demo ids found in `path` (new or already known)."""
    path = Path(path)
    if path.is_dir():
        return [d for p in sorted(path.iterdir()) for d in ingest(p)]
    suffix = path.suffix.lower()
    if suffix == ".dem":
        d = _add_dem(path, path.name)
        return [d] if d else []
    if suffix in ARCHIVES:
        with tempfile.TemporaryDirectory() as tmp:
            _extract(path, Path(tmp))
            ids = []
            for dem in sorted(Path(tmp).rglob("*.dem")):
                d = _add_dem(dem, f"{path.stem}-{dem.name}")
                if d:
                    ids.append(d)
            return ids
    return []
