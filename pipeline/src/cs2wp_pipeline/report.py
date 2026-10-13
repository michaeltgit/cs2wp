"""Batch report: Kalshi comparison across all demos."""

import numpy as np
import pandas as pd

from cs2wp_core import db
from cs2wp_core.config import DATA

from . import kalshi
from .parse import load_meta


def kalshi_all(relink: bool = False, log=print) -> pd.DataFrame:
    """Auto-link every demo to its Kalshi map market (if any) and collect the comparison."""
    from cs2wp_core.modeling import match_key

    from .jobs import link_match
    rows = []
    ids = [r["id"] for r in db.rows("SELECT id FROM demos WHERE status='ready' ORDER BY id")]
    # whole matches at a time, so every map of a match links to the same Kalshi match
    todo = sorted({match_key(d) for d in ids if relink or kalshi.link_info(d) is None})
    status = {}
    for i, key in enumerate(todo, 1):
        status.update(link_match(key))
        log(f"[{i}/{len(todo)}] {key[:60]}: " + ", ".join(sorted(set(status[d] for d in ids if match_key(d) == key))))
    for d in ids:
        if status.get(d, "linked") != "linked":
            continue
        if d not in status:
            db.update_demo(d, kalshi_status="linked", kalshi_confidence=kalshi.alignment_quality(d).get("confidence"))
        a = kalshi.analysis(d)
        if not a or not a.get("n_seconds"):
            continue
        meta = load_meta(d)
        rows.append({"demo": d, "map": meta["map"], "a": a["teams"]["a"]["name"], "b": a["teams"]["b"]["name"],
                     "final": a["final"], "gap": a["mean_abs_gap"], "bias": a["mean_gap"], "corr": a["level_corr"],
                     "brier_model": a["brier_ours"], "brier_market": a["brier_market"],
                     "jump_corr": a["lag_corr"], "lag": a["lag_secs"], "seconds": a["n_seconds"], "trades": a["n_trades"]})
        log(f"linked     {d[:60]}  gap {a['mean_abs_gap']:.3f}  brier model {a['brier_ours']:.3f} vs market {a['brier_market']:.3f}")
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(DATA / "kalshi_report.csv", index=False)
    return df


def summarize(df: pd.DataFrame) -> dict:
    w = df["seconds"].to_numpy()
    return {
        "maps": int(len(df)),
        "model_better_on": int((df["brier_model"] < df["brier_market"]).sum()),
        "brier_model": round(float(np.average(df["brier_model"], weights=w)), 4),
        "brier_market": round(float(np.average(df["brier_market"], weights=w)), 4),
        "avg_gap_pts": round(float(np.average(df["gap"], weights=w)) * 100, 1),
        "avg_bias_pts": round(float(np.average(df["bias"], weights=w)) * 100, 1),
        "median_jump_corr": round(float(df["jump_corr"].median()), 3),
    }
