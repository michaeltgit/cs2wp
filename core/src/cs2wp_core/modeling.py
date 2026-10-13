"""Model registry + prediction (shared by pipeline scoring, the live runtime and the API).

Artifacts live under ``models/`` in object storage:

    models/registry.json                    {"active": "v008", "versions": {...}}
    models/<v>/model.txt                    LightGBM booster (deployed model, trained on all matches)
    models/<v>/calibrator.pkl               isotonic calibration
    models/<v>/features.json                feature list, maps, CT round rate per map
    models/<v>/train_matches.json           which matches it was trained on (in/out-of-sample label)
    models/<v>/train_fingerprints.json      {map fingerprint: match key}: recognises a re-uploaded map
    models/<v>/metrics.json, calibration.png, baseline.json
    models/<v>/cv/<match_key>/...           leave-one-match-out model for that match (same files)

``predictor_for(demo_id)`` returns the leave-one-match-out model when one exists for the demo's
match, so historical timelines are always scored out-of-sample; new matches use the deployed model
(which never saw them either).
"""

from __future__ import annotations

import json
import pickle
from functools import lru_cache

import numpy as np
import pandas as pd

from . import storage
from .features import FEATURES

CATEGORICAL = ["map"]
MONOTONE = {"ct_alive": 1, "t_alive": -1, "ct_hp": 1, "t_hp": -1, "ct_kits": 1}
# Grouped-CV ablation (31 matches): score context inside the ROUND model let it recognise individual
# matches (overfit); removing it improved held-out log loss. The round model sees game state only.
MODEL_EXCLUDE = {"round_num", "ct_score", "t_score", "score_diff"}
MODEL_FEATURES = [f for f in FEATURES if f not in MODEL_EXCLUDE]

REGISTRY_KEY = "models/registry.json"
ARTIFACTS = ["model.txt", "calibrator.pkl", "features.json"]


def match_key(demo_id: str) -> str:
    """Maps from one archive (one match) share everything but the trailing '-<sha8>'."""
    return demo_id.rsplit("-", 1)[0]


def registry() -> dict:
    p = storage.local_path(REGISTRY_KEY)  # revalidated against S3 by ETag (other services change it)
    if p.exists():
        return json.loads(p.read_text())
    return {"active": None, "versions": {}}


def save_registry(reg: dict) -> None:
    p = storage.local_path(REGISTRY_KEY, fetch=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, indent=1))
    storage.publish(REGISTRY_KEY)
    _load.cache_clear()


def set_active(version: str) -> None:
    reg = registry()
    if version not in reg["versions"]:
        raise KeyError(version)
    reg["active"] = version
    save_registry(reg)


def design_matrix(df: pd.DataFrame, maps, feats=None) -> pd.DataFrame:
    """Columns in the order the model was trained on; features it never saw are dropped,
    features it expects but the data lacks become NaN (so older model versions keep working)."""
    X = df.reindex(columns=feats if feats is not None else MODEL_FEATURES).copy()
    if "map" in X:
        X["map"] = pd.Categorical(X["map"], categories=maps)
    return X


class Predictor:
    """A trained round model + calibrator + the map-level settings it was fitted with."""

    def __init__(self, booster, cal, info: dict, version: str, train_matches=None, oos: bool = False,
                 fingerprints: dict | None = None):
        self.booster, self.cal, self.version = booster, cal, version
        self.maps = info["maps"]
        self.features = info.get("features", MODEL_FEATURES)
        self.ct_rate = info.get("ct_round_rate", {})
        self.train_matches = train_matches  # set | "unknown" | None (None = leave-one-match-out)
        self.oos = oos
        self.fingerprints = fingerprints or {}

    def kind_for(self, demo_id: str, fingerprint: str | None = None) -> str:
        """'out-of-sample' unless this model was trained on the demo's match (by id, or by the map's
        content fingerprint, so the same map uploaded again under another name is still caught)."""
        if self.oos or self.train_matches is None:
            return "out-of-sample"
        if self.train_matches == "unknown":
            return "unknown"
        seen = match_key(demo_id) in self.train_matches or (fingerprint is not None and fingerprint in self.fingerprints)
        return "in-sample" if seen else "out-of-sample"

    def q_ct(self, map_name: str) -> float:
        """CT round win rate on this map (shrunk toward 0.5), used for future rounds."""
        return self.ct_rate.get(map_name, 0.5)

    def predict(self, feats: pd.DataFrame) -> np.ndarray:
        if feats.empty:
            return np.array([])
        return self.cal.predict(self.booster.predict(design_matrix(feats, self.maps, self.features)))


@lru_cache(maxsize=64)
def _load(prefix: str, version: str, oos: bool) -> Predictor:
    import lightgbm as lgb
    paths = {a: storage.local_path(f"{prefix}/{a}") for a in ARTIFACTS}
    if not paths["model.txt"].exists():
        raise FileNotFoundError(f"{prefix}/model.txt")
    booster = lgb.Booster(model_file=str(paths["model.txt"]))
    cal = pickle.loads(paths["calibrator.pkl"].read_bytes())
    info = json.loads(paths["features.json"].read_text())
    tm = storage.local_path(f"{prefix}/train_matches.json")
    train = set(json.loads(tm.read_text())) if tm.exists() else ("unknown" if not oos else None)
    fp = storage.local_path(f"{prefix}/train_fingerprints.json")
    fps = json.loads(fp.read_text()) if fp.exists() else {}
    return Predictor(booster, cal, info, version, train, oos, fps)


def load_predictor(version: str | None = None) -> Predictor:
    version = version or registry()["active"]
    if version is None:
        raise RuntimeError("no trained model yet")
    return _load(f"models/{version}", version, False)


def predictor_for(demo_id: str, version: str | None = None, fingerprint: str | None = None) -> Predictor:
    """Out-of-sample model for this demo's match if the registry has one, else the deployed model.
    ``fingerprint`` (meta.json) finds the match of a map that was trained on under another id."""
    version = version or registry()["active"]
    if version is None:
        raise RuntimeError("no trained model yet")
    deployed = _load(f"models/{version}", version, False)
    for mk in (match_key(demo_id), deployed.fingerprints.get(fingerprint) if fingerprint else None):
        cv = f"models/{version}/cv/{mk}"
        if mk and storage.exists(f"{cv}/model.txt"):
            return _load(cv, f"{version}:cv", True)
    return deployed
