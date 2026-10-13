"""Validation gate: the live path must give the same answers as batch scoring.

Batch: features for the whole demo at once -> model. Live: the replay streamer cuts a round into
RawGS frames (as at real playback speeds), each frame goes through JSON like a Kafka message,
then the live inference step builds features from that frame alone -> model. For every tick both
paths produce, features and P(CT wins the round) must match. A GRID adapter emits the same frames,
so this is also the check to run against real GRID data before trusting it.
"""

from __future__ import annotations

import json

import numpy as np

from cs2wp_core import features
from cs2wp_core.modeling import predictor_for

from .parse import load
from .runtime import ReplayStreamer, infer_frame

CHUNKS = (1, 7, 17, 64)  # ticks per frame: paused stepping up to fast-forward


def live_vs_batch(demo_id: str, rounds: list[int] | None = None, predictor=None, tol: float = 1e-6,
                  chunks: tuple[int, ...] = CHUNKS) -> dict:
    meta, ticks, events = load(demo_id)
    pred = predictor or predictor_for(demo_id, fingerprint=meta.get("fingerprint"))
    batch = features.build(meta, ticks, events, every=1)
    batch["p_ct"] = pred.predict(batch) if len(batch) else []
    batch = batch.set_index(["round", "tick"])
    cols = [c for c in getattr(pred, "features", features.FEATURES) if c != "map"]

    rounds = rounds or [r["round"] for r in meta["rounds"]]
    worst_feat, worst_p, n, bad = 0.0, 0.0, 0, []
    for i, rnd in enumerate(rounds):
        streamer = ReplayStreamer(f"validate-{rnd}", demo_id, rnd)
        chunk = chunks[i % len(chunks)]
        tl = streamer.tick_list
        for k in range(0, len(tl), chunk):
            frame = json.loads(json.dumps(streamer.frame(tl[k:k + chunk])))  # through the wire format
            f, p = infer_frame(frame, pred)
            if not len(f):
                continue
            f = f.assign(p_ct=p).set_index(["round", "tick"])
            both = f.index.intersection(batch.index)
            if not len(both):
                continue
            a, b = batch.loc[both], f.loc[both]
            dfeat = max((np.nanmax(np.abs(a[c].astype(float).to_numpy() - b[c].astype(float).to_numpy()), initial=0.0)
                         for c in cols if c in b), default=0.0)
            nan_mismatch = [c for c in cols if c in b and
                            (np.isnan(a[c].astype(float).to_numpy()) != np.isnan(b[c].astype(float).to_numpy())).any()]
            dp = float(np.nanmax(np.abs(a["p_ct"].to_numpy() - b["p_ct"].to_numpy()), initial=0.0))
            worst_feat, worst_p, n = max(worst_feat, dfeat), max(worst_p, dp), n + len(both)
            if dfeat > tol or dp > tol or nan_mismatch:
                bad.append({"round": int(rnd), "ticks": [int(x) for x in both.get_level_values("tick")[:3]],
                            "max_feature_diff": dfeat, "max_p_diff": dp, "nan_mismatch": nan_mismatch})
    return {"demo_id": demo_id, "model": getattr(pred, "version", "?"), "rounds": len(rounds), "ticks_compared": n,
            "max_feature_diff": worst_feat, "max_p_diff": worst_p, "ok": not bad and n > 0, "mismatches": bad[:10]}
