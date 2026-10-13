"""Baseline model + probability metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

BASELINE_KEY = ["ct_alive", "t_alive", "bomb_planted"]


def fit_baseline(df: pd.DataFrame, alpha: float = 5.0) -> dict:
    """Smoothed CT win rate per (alive, alive, planted) cell: the number to beat."""
    prior = float(np.average(df["ct_win"], weights=df["w"]))
    g = df.assign(wy=df["ct_win"] * df["w"]).groupby(BASELINE_KEY).agg(wy=("wy", "sum"), w=("w", "sum"))
    table = ((g["wy"] + alpha * prior) / (g["w"] + alpha)).rename("p").reset_index()
    return {"prior": prior, "table": table.to_dict("records")}


def predict_baseline(b: dict, df: pd.DataFrame) -> np.ndarray:
    t = pd.DataFrame(b["table"])
    m = df[BASELINE_KEY].merge(t, on=BASELINE_KEY, how="left")
    return m["p"].fillna(b["prior"]).to_numpy()


def metrics(y, p, w) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    ll = -np.average(y * np.log(p) + (1 - y) * np.log(1 - p), weights=w)
    brier = np.average((p - y) ** 2, weights=w)
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(abs(np.average(y[bins == b], weights=w[bins == b]) - np.average(p[bins == b], weights=w[bins == b]))
              * w[bins == b].sum() for b in range(10) if (bins == b).any()) / w.sum()
    acc = np.average((p > 0.5) == (y == 1), weights=w)
    return {"log_loss": round(float(ll), 4), "brier": round(float(brier), 4),
            "ece": round(float(ece), 4), "accuracy": round(float(acc), 4)}
