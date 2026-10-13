"""Batch scoring: P(CT win) for every tick, win-prob swing for each event, Win Probability Added per player."""

import json

import numpy as np
import pandas as pd

from cs2wp_core import mapwin, storage
from cs2wp_core.config import CT, SCORES
from cs2wp_core.modeling import Predictor, predictor_for

SWING_EVENTS = {"kill", "plant", "defuse_start", "defuse", "explode"}


def score_demo(demo_id: str, predictor: Predictor | None = None) -> dict:
    # default: the leave-one-match-out model for this match if the registry has one (out-of-sample)
    from .parse import load
    meta, _, events = load(demo_id)
    predictor = predictor or predictor_for(demo_id, fingerprint=meta.get("fingerprint"))
    feats = pd.read_parquet(storage.local_path(f"features/{demo_id}.parquet"))

    p = predictor.predict(feats)
    scores = feats[["round", "tick"]].assign(p_ct=p.astype(np.float32))
    # map win probability for team A (Kalshi map markets price this)
    q = predictor.q_ct(meta["map"])
    rinfo = {r["round"]: r for r in meta["rounds"]}
    scores["p_map_a"] = np.array([
        mapwin.map_win_prob(rinfo[rd]["a_score"], rinfo[rd]["b_score"], rinfo[rd]["a_is_ct"],
                            pc if rinfo[rd]["a_is_ct"] else 1 - pc, q)
        for rd, pc in zip(scores["round"], scores["p_ct"])], dtype=np.float32)
    SCORES.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(SCORES / f"{demo_id}.parquet", index=False)

    outcome = {r["round"]: float(r["winner"] == CT) for r in meta["rounds"]}
    ev = events[events["type"].isin(SWING_EVENTS)].copy()
    before, after = [], []
    for rnd, tick in zip(ev["round"], ev["tick"]):
        s = scores[scores["round"] == rnd]
        t, pp = s["tick"].to_numpy(), s["p_ct"].to_numpy()
        i = np.searchsorted(t, tick, side="left")      # first tick >= event
        before.append(float(pp[i - 1]) if i > 0 else np.nan)
        j = np.searchsorted(t, tick, side="right")     # first tick > event
        after.append(float(pp[j]) if j < len(t) else outcome.get(rnd, np.nan))
    ev["p_before"], ev["p_after"] = before, after
    ev["swing_ct"] = ev["p_after"] - ev["p_before"]
    ev.to_parquet(SCORES / f"{demo_id}_events.parquet", index=False)

    # WPA: actor gets the swing from their own side's point of view, kill victims lose it
    names = {pl["steamid"]: pl["name"] for pl in meta["players"]}
    wpa: dict[str, dict] = {sid: {"steamid": sid, "name": n, "wpa": 0.0, "kills": 0, "deaths": 0,
                                  "plants": 0, "defuses": 0} for sid, n in names.items()}
    for _, e in ev.dropna(subset=["swing_ct"]).iterrows():
        side_sign = lambda team: 1.0 if team == CT else -1.0  # noqa: E731
        a = e.get("actor_steamid")
        if a in wpa and pd.notna(e.get("actor_team")):
            wpa[a]["wpa"] += side_sign(e["actor_team"]) * e["swing_ct"]
            key = {"kill": "kills", "plant": "plants", "defuse": "defuses"}.get(e["type"])
            if key:
                wpa[a][key] += 1
        if e["type"] == "kill":
            v = e.get("victim_steamid")
            if v in wpa and pd.notna(e.get("victim_team")):
                wpa[v]["wpa"] += side_sign(e["victim_team"]) * e["swing_ct"]
                wpa[v]["deaths"] += 1
    table = sorted(wpa.values(), key=lambda r: -r["wpa"])
    for r in table:
        r["wpa"] = round(r["wpa"], 3)
    kind = predictor.kind_for(demo_id, meta.get("fingerprint")) if hasattr(predictor, "kind_for") else "unknown"
    (SCORES / f"{demo_id}_wpa.json").write_text(json.dumps({"model": predictor.version, "kind": kind, "players": table}))
    storage.publish(*(f"scores/{demo_id}{suffix}" for suffix in (".parquet", "_events.parquet", "_wpa.json")))
    from cs2wp_core import db
    db.update_demo(demo_id, score_model=predictor.version, score_kind=kind)
    return {"model": predictor.version, "n_ticks": len(scores)}
