"""Training on a small synthetic dataset: registry, leave-one-match-out models, out-of-sample routing."""

import json

import numpy as np
import pandas as pd
import pytest

from cs2wp_core import modeling, storage
from cs2wp_core.features import FEATURES
from cs2wp_ml import train as T
from cs2wp_ml.metrics import fit_baseline, metrics, predict_baseline

MATCHES = ["evt-a-vs-b-bo3-k1", "evt-c-vs-d-bo3-k2", "evt-e-vs-f-bo3-k3", "evt-g-vs-h-bo3-k4"]


def _synthetic(rng, demo_id, map_name, n_rounds=24, n_ticks=40):
    rows = []
    for r in range(1, n_rounds + 1):
        ct_win = int(rng.random() < 0.5)
        for k in range(n_ticks):
            prog = k / n_ticks
            # the winning side keeps more players alive as the round goes on (a learnable signal)
            ct_alive = 5 - int(prog * rng.integers(0, 4) * (1 - ct_win))
            t_alive = 5 - int(prog * rng.integers(0, 4) * ct_win)
            row = {f: 0.0 for f in FEATURES}
            row.update(map=map_name, ct_alive=ct_alive, t_alive=t_alive, alive_diff=ct_alive - t_alive,
                       ct_hp=ct_alive * 100, t_hp=t_alive * 100, round_time_left=115 - prog * 100,
                       bomb_planted=0)
            rows.append({**row, "demo_id": demo_id, "round": r, "tick": 1000 * r + k, "ct_win": ct_win,
                         "valid": True})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def dataset():
    rng = np.random.default_rng(1)
    ids = []
    for i, mk in enumerate(MATCHES):
        for j, m in enumerate(["de_mirage", "de_inferno"]):
            d = f"{mk}-{i}{j}abcdef"
            p = storage.local_path(f"features/{d}.parquet", fetch=False)
            p.parent.mkdir(parents=True, exist_ok=True)
            _synthetic(rng, d, m).to_parquet(p, index=False)
            meta = storage.local_path(f"parsed/{d}/meta.json", fetch=False)
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text(json.dumps({"fingerprint": f"fp-{d}", "rounds": list(range(24))}))
            ids.append(d)
    return ids


def test_metrics_and_baseline():
    y = np.array([1, 0, 1, 0])
    w = np.ones(4)
    assert metrics(y, np.array([0.9, 0.1, 0.8, 0.2]), w)["log_loss"] < metrics(y, np.full(4, 0.5), w)["log_loss"]
    df = pd.DataFrame({"ct_alive": [5, 5, 1], "t_alive": [1, 1, 5], "bomb_planted": [0, 0, 0],
                       "ct_win": [1, 1, 0], "w": [1.0, 1.0, 1.0]})
    p = predict_baseline(fit_baseline(df), df)
    assert p[0] > p[2]  # sparse cells are shrunk toward the prior, but the order holds


def test_train_registers_version_with_cv_models(dataset):
    v = T.train(activate=True, every=1, rounds=20, log=lambda *_: None)
    reg = modeling.registry()
    assert reg["active"] == v and reg["versions"][v]["n_cv_models"] == len(MATCHES)
    m = json.loads(storage.local_path(f"models/{v}/metrics.json").read_text())
    assert m["held_out"] and m["n_matches"] == len(MATCHES)
    assert m["overall"]["lightgbm_calibrated"]["log_loss"] < 0.69  # learned something real
    assert sorted(json.loads(storage.local_path(f"models/{v}/train_matches.json").read_text())) == MATCHES

    # historical demos are scored by the model that never saw their match
    d = dataset[0]
    p = modeling.predictor_for(d)
    assert p.version == f"{v}:cv" and p.kind_for(d) == "out-of-sample"
    feats = pd.read_parquet(storage.local_path(f"features/{d}.parquet"))
    pr = p.predict(feats)
    assert len(pr) == len(feats) and np.all((pr > 0) & (pr < 1))

    # a brand-new match falls back to the deployed model, which never saw it either
    q = modeling.predictor_for("other-event-x-vs-y-bo3-zz-12345678")
    assert q.version == v and q.kind_for("other-event-x-vs-y-bo3-zz-12345678") == "out-of-sample"
    assert q.kind_for(d) == "in-sample"

    # the same map re-uploaded under another id is recognised by its content fingerprint
    again = "fresh-upload-a-vs-b-bo3-k9-deadbeef"
    assert modeling.predictor_for(again, fingerprint=f"fp-{d}").version == f"{v}:cv"
    assert q.kind_for(again, f"fp-{d}") == "in-sample" and q.kind_for(again) == "out-of-sample"


def test_versions_increment_and_activation(dataset):
    before = modeling.registry()["active"]
    v = T.train(activate=False, every=1, rounds=10, cv_models=False, log=lambda *_: None)
    reg = modeling.registry()
    assert reg["active"] == before and v != before
    modeling.set_active(v)
    assert modeling.registry()["active"] == v
    with pytest.raises(KeyError):
        modeling.set_active("v999")
