"""Training data: one feature file per map from object storage (``features/<demo_id>.parquet``)."""

from __future__ import annotations

import json

import pandas as pd

from cs2wp_core import storage
from cs2wp_core.config import TRAIN_EVERY

# Matches left out of training (they are still scored and shown). Keys are match-key prefixes.
EXCLUDED_MATCHES = {
    "test-demo": "demoparser2's public sample demo, not a known pro match",
    "d30d29bf-uesf-championship-of-ukraine": "tier-3 event; Kalshi only lists tier-1/2 matches",
}
REGULATION_ROUNDS = 24  # MR12: rounds after 12-12 are overtime ($10k start money); left out for now


def excluded(demo_id: str) -> bool:
    return any(demo_id.startswith(k) for k in EXCLUDED_MATCHES)


def feature_ids() -> list[str]:
    return sorted(d for d in (k.rsplit("/", 1)[-1][: -len(".parquet")] for k in storage.store().list("features/")
                              if k.endswith(".parquet")) if not excluded(d))


def _meta(demo_id: str) -> dict:
    p = storage.local_path(f"parsed/{demo_id}/meta.json")
    return json.loads(p.read_text()) if p.exists() else {}


def load_dataset(every: int = TRAIN_EVERY, ids: list[str] | None = None) -> pd.DataFrame:
    """Valid regulation-time snapshots subsampled to ``every`` ticks; each round weighs 1 regardless of length.
    Excluded matches (EXCLUDED_MATCHES) are skipped.
    If the same map was uploaded twice (same fingerprint) only the copy with most rounds is kept."""
    best: dict[str, tuple[int, str]] = {}
    for d in ids if ids is not None else feature_ids():
        meta = _meta(d)
        key = meta.get("fingerprint") or d
        n = len(meta.get("rounds", []))
        if key not in best or n > best[key][0]:
            best[key] = (n, d)
    frames = []
    for _, d in sorted(best.values(), key=lambda x: x[1]):
        f = pd.read_parquet(storage.local_path(f"features/{d}.parquet"))
        f = f[f["valid"] & ((f["ct_score"] + f["t_score"]) < REGULATION_ROUNDS)]  # no overtime rounds
        if every > 1:
            first = f.groupby("round")["tick"].transform("min")
            f = f[(f["tick"] - first) % every == 0]
        frames.append(f)
    if not frames:
        raise ValueError("no feature files; process some demos first")
    df = pd.concat(frames, ignore_index=True)
    df["w"] = 1.0 / df.groupby(["demo_id", "round"])["tick"].transform("size")
    return df
