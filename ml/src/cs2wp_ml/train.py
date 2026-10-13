"""Training: grouped-by-match CV metrics, the deployed model, and one leave-one-match-out model
per match (so every historical timeline and Kalshi comparison is scored out-of-sample).

Everything is written under ``models/<version>/`` and published to object storage; the registry
(``models/registry.json``) is updated last, so readers never see a half-written version.
"""

from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import lightgbm as lgb
import matplotlib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold

from cs2wp_core import modeling, storage
from cs2wp_core.config import TRAIN_EVERY
from cs2wp_core.modeling import CATEGORICAL, MODEL_FEATURES, MONOTONE, design_matrix, match_key

from .dataset import _meta, load_dataset
from .metrics import fit_baseline, metrics, predict_baseline

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

N_ROUNDS = 400


def lgb_params(n_rows: int, feats=None) -> dict:
    feats = feats if feats is not None else MODEL_FEATURES
    return dict(objective="binary", learning_rate=0.05, num_leaves=31,
                min_data_in_leaf=int(max(20, min(400, n_rows / 100))),
                feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
                monotone_constraints=[MONOTONE.get(f, 0) for f in feats],
                verbose=-1, seed=7)


def fit_lgb(X, y, w, rounds: int = N_ROUNDS, feats=None):
    cat = [c for c in CATEGORICAL if c in X.columns] or "auto"
    ds = lgb.Dataset(X, y, weight=w, categorical_feature=cat, free_raw_data=False)
    return lgb.train(lgb_params(len(X), feats), ds, num_boost_round=rounds)


def isotonic():
    return IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)


def ct_round_rate(df) -> dict:
    rounds = df.groupby(["demo_id", "round"]).agg(map=("map", "first"), y=("ct_win", "first"))
    return {m: round(float((g["y"].sum() + 10 * 0.5) / (len(g) + 10)), 4) for m, g in rounds.groupby("map")}


def _write_artifacts(prefix: str, booster, cal, info: dict, extra: dict | None = None) -> list[str]:
    out = storage.local_path(prefix, fetch=False)
    out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out / "model.txt"))
    (out / "calibrator.pkl").write_bytes(pickle.dumps(cal))
    (out / "features.json").write_text(json.dumps(info))
    for name, obj in (extra or {}).items():
        (out / name).write_text(json.dumps(obj, indent=1))
    return [f"{prefix}/{p.name}" for p in out.iterdir() if p.is_file()]


def _calibration_plot(y, w, preds: dict, path: Path):
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    for name, p in preds.items():
        bins = np.minimum((p * 10).astype(int), 9)
        xs, ys = [], []
        for b in range(10):
            m = bins == b
            if m.sum() > 0:
                xs.append(np.average(p[m], weights=w[m]))
                ys.append(np.average(y[m], weights=w[m]))
        ax.plot(xs, ys, marker="o", label=name)
    ax.set_xlabel("predicted P(CT wins round)")
    ax.set_ylabel("actual CT win rate")
    ax.legend()
    ax.set_title("Calibration (held-out matches)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _next_version(reg: dict) -> str:
    nums = [int(v[1:]) for v in reg["versions"] if v[1:].isdigit()]
    return f"v{max(nums, default=0) + 1:03d}"


def train(activate: bool = False, every: int = TRAIN_EVERY, cv_models: bool = True, rounds: int = N_ROUNDS,
          log=print, progress=None) -> str:
    """Train a new version. ``progress(stage)`` is called with human-readable stages (job status)."""
    progress = progress or (lambda s: None)
    df = load_dataset(every)
    maps = sorted(df["map"].unique().tolist())
    y, w = df["ct_win"].to_numpy(), df["w"].to_numpy()
    groups = df["demo_id"].map(match_key).to_numpy()  # split by MATCH: sister maps share teams
    matches = sorted(set(groups))
    n_demos, n_matches = df["demo_id"].nunique(), len(matches)
    X = design_matrix(df, maps)
    log(f"dataset: {len(df)} snapshots, {df.groupby(['demo_id', 'round']).ngroups} rounds, "
        f"{n_demos} maps, {n_matches} matches")

    oof_lgb, oof_base = np.zeros(len(df)), np.zeros(len(df))
    held_out = n_matches >= 2
    if held_out:
        folds = GroupKFold(n_splits=min(5, n_matches)).split(X, y, groups)
        for k, (tr, te) in enumerate(folds):
            progress(f"cv fold {k + 1}/{min(5, n_matches)}")
            m = fit_lgb(X.iloc[tr], y[tr], w[tr], rounds)
            oof_lgb[te] = m.predict(X.iloc[te])
            oof_base[te] = predict_baseline(fit_baseline(df.iloc[tr]), df.iloc[te])
            log(f"fold {k + 1} done")
    progress("final model")
    final = fit_lgb(X, y, w, rounds)
    base = fit_baseline(df)
    if not held_out:
        log("WARNING: only 1 match, metrics are in-sample and meaningless; add more demos")
        oof_lgb, oof_base = final.predict(X), predict_baseline(base, df)

    # honest calibrated metrics: each match's calibrator is fitted on the OTHER matches' predictions
    oof_cal = np.zeros(len(df))
    if held_out:
        for g in matches:
            m = groups == g
            oof_cal[m] = isotonic().fit(oof_lgb[~m], y[~m], sample_weight=w[~m]).predict(oof_lgb[m])
    cal = isotonic().fit(oof_lgb, y, sample_weight=w)  # the deployed calibrator uses everything
    if not held_out:
        oof_cal = cal.predict(oof_lgb)

    planted = df["bomb_planted"].to_numpy() == 1
    res = {
        "held_out": held_out, "n_demos": n_demos, "n_matches": n_matches, "n_snapshots": int(len(df)),
        "n_rounds": int(df.groupby(["demo_id", "round"]).ngroups), "maps": maps, "train_every_ticks": every,
        "overall": {"baseline": metrics(y, oof_base, w), "lightgbm": metrics(y, oof_lgb, w),
                    "lightgbm_calibrated": metrics(y, oof_cal, w)},
        "pre_plant": {"baseline": metrics(y[~planted], oof_base[~planted], w[~planted]),
                      "lightgbm_calibrated": metrics(y[~planted], oof_cal[~planted], w[~planted])},
    }
    if planted.any():
        res["post_plant"] = {"baseline": metrics(y[planted], oof_base[planted], w[planted]),
                             "lightgbm_calibrated": metrics(y[planted], oof_cal[planted], w[planted])}
    imp = final.feature_importance("gain")
    res["feature_importance"] = dict(sorted(
        {f: round(float(v), 1) for f, v in zip(MODEL_FEATURES, imp)}.items(), key=lambda kv: -kv[1]))

    reg = modeling.registry()
    version = _next_version(reg)
    prefix = f"models/{version}"
    info = {"features": MODEL_FEATURES, "maps": maps, "ct_round_rate": ct_round_rate(df)}
    fingerprints = {fp: match_key(d) for d in df["demo_id"].unique() if (fp := _meta(d).get("fingerprint"))}
    keys = _write_artifacts(prefix, final, cal, info,
                            {"metrics.json": res, "baseline.json": base, "train_matches.json": matches,
                             "train_fingerprints.json": fingerprints})
    out = storage.local_path(prefix, fetch=False)
    _calibration_plot(y, w, {"baseline": oof_base, "lightgbm (calibrated)": oof_cal}, out / "calibration.png")
    keys.append(f"{prefix}/calibration.png")

    n_cv = 0
    if cv_models and held_out:
        # leave-one-match-out: each model never saw its match. Its calibrator is fitted on the OTHER
        # matches' out-of-fold predictions, never on the booster's own training predictions: those are
        # overconfident, and calibrating on them pushed stored timelines to 0.60 log loss (vs 0.46).
        for i, mk in enumerate(matches, 1):
            progress(f"leave-one-match-out {i}/{n_matches}")
            tr = groups != mk
            sub = df[tr]
            booster = fit_lgb(X[tr], y[tr], w[tr], rounds)
            c = isotonic().fit(oof_lgb[tr], y[tr], sample_weight=w[tr])
            sinfo = {"features": MODEL_FEATURES, "maps": maps, "ct_round_rate": ct_round_rate(sub),
                     "excluded_match": mk}
            keys += _write_artifacts(f"{prefix}/cv/{mk}", booster, c, sinfo)
            n_cv += 1
        log(f"{n_cv} leave-one-match-out models")
    res["n_cv_models"] = n_cv
    (out / "metrics.json").write_text(json.dumps(res, indent=1))

    progress("publishing")
    storage.publish(*sorted(set(keys)))
    reg = modeling.registry()  # re-read: another trainer may have registered meanwhile
    reg["versions"][version] = {"created": time.time(), "n_demos": n_demos, "n_matches": n_matches,
                                "n_rounds": res["n_rounds"], "held_out": held_out, "n_cv_models": n_cv,
                                "overall": res["overall"]}
    if activate or reg["active"] is None:
        reg["active"] = version
    modeling.save_registry(reg)
    log(json.dumps(res["overall"], indent=1))
    return version
