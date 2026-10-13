"""Evaluation beyond the training report: feature-group ablation and per-match held-out scores."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from cs2wp_core.features import FEATURES
from cs2wp_core.modeling import MODEL_FEATURES, design_matrix, match_key

from .dataset import load_dataset
from .metrics import metrics
from .train import fit_lgb, isotonic

GROUPS = {
    "alive": ["ct_alive", "t_alive", "alive_diff"],
    "hp_armor": ["ct_hp", "t_hp", "ct_armor", "t_armor", "ct_helmets", "t_helmets"],
    "economy": ["ct_equip", "t_equip", "equip_diff", "ct_money", "t_money"],
    "weapons": [f for f in FEATURES if any(w in f for w in ("rifle", "awp", "scout", "smg", "heavy"))],
    "utility": [f for f in FEATURES if any(w in f for w in ("smokes", "flashes", "molos", "hes"))],
    "bomb": ["bomb_planted", "bomb_time_left", "defusing", "defusing_with_kit", "bomb_dropped",
             "t_carrier_alive", "carrier_in_zone", "t_in_zone", "ct_kits"],
    "positions": ["ct_min_dist_bomb", "ct_near_bomb", "t_near_bomb", "t_min_dist_site", "ct_min_dist_site",
                  "carrier_dist_site"],
    "time": ["round_time_left", "secs_since_kill"],
    "score_context": ["round_num", "ct_score", "t_score", "score_diff"],
    "map": ["map"],
}


def _oof(df, feats, rounds=300, folds=5):
    """Grouped-by-match out-of-fold predictions, calibrated per match on the other matches."""
    maps = sorted(df["map"].unique().tolist())
    y, w = df["ct_win"].to_numpy(), df["w"].to_numpy()
    g = df["demo_id"].map(match_key).to_numpy()
    X = design_matrix(df, maps, feats)
    oof = np.zeros(len(df))
    for tr, te in GroupKFold(min(folds, len(set(g)))).split(X, y, g):
        oof[te] = fit_lgb(X.iloc[tr], y[tr], w[tr], rounds, feats).predict(X.iloc[te])
    cal = np.zeros(len(df))
    for d in np.unique(g):
        m = g == d
        cal[m] = isotonic().fit(oof[~m], y[~m], sample_weight=w[~m]).predict(oof[m])
    return cal, y, w, g


def ablation(log=print, every: int = 16) -> pd.DataFrame:
    """Held-out log loss with each feature group removed, starting from ALL features (including the
    ones the deployed model excludes) so the table shows why they are excluded."""
    df = load_dataset(every=every)
    base, y, w, _ = _oof(df, FEATURES)
    base_ll = metrics(y, base, w)["log_loss"]
    rows = [{"removed": "(none)", "log_loss": base_ll, "delta": 0.0}]
    log(f"all features: {base_ll:.4f}")
    for name, cols in GROUPS.items():
        p, *_ = _oof(df, [f for f in FEATURES if f not in cols])
        ll = metrics(y, p, w)["log_loss"]
        rows.append({"removed": name, "log_loss": ll, "delta": round(ll - base_ll, 4)})
        log(f"without {name:14s} {ll:.4f}  ({ll - base_ll:+.4f})")
    return pd.DataFrame(rows).sort_values("delta", ascending=False)


def by_match(every: int = 16) -> pd.DataFrame:
    """Held-out log loss per match for the deployed feature set (spots matches the model finds hard)."""
    df = load_dataset(every=every)
    p, y, w, g = _oof(df, MODEL_FEATURES)
    rows = []
    for mk in np.unique(g):
        m = g == mk
        rows.append({"match": mk, "rounds": int(df[m].groupby(["demo_id", "round"]).ngroups),
                     **metrics(y[m], p[m], w[m])})
    return pd.DataFrame(rows).sort_values("log_loss", ascending=False)
