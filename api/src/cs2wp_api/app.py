"""FastAPI service: demos, jobs, replay data, models, Kalshi comparison, live WebSocket gateway.

Read-only apart from switching the active model (which queues a ``rescore`` job). Adding, deleting
and reprocessing demos, training and Kalshi linking are backend commands (``cs2wp-pipeline``,
``cs2wp-ml``), never web endpoints. Workers claim jobs from the jobs table. In lite mode (SQLite, ``CS2WP_EMBEDDED_WORKERS=1``) those workers
run as threads inside this process so one command gives a working system.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cs2wp_core import config, db, modeling, storage
from cs2wp_core.config import CACHE, TICKRATE
from cs2wp_core.modeling import match_key
from cs2wp_pipeline import jobs as pjobs

from . import live
from .util import clean


def _embedded() -> bool:
    default = "1" if db.engine().dialect.name == "sqlite" else "0"
    return os.environ.get("CS2WP_EMBEDDED_WORKERS", default) == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    stop = threading.Event()
    if _embedded():
        # lite mode: pipeline + ml workers and the inbox watcher run inside the API process
        from cs2wp_ml.worker import run_forever as ml_forever
        pjobs.Worker(threads=int(os.environ.get("CS2WP_WORKER_THREADS", "3"))).start()
        config.INBOX.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=pjobs.watch_inbox, args=(stop,), daemon=True, name="cs2wp-inbox").start()
        threading.Thread(target=pjobs.watch_uploads, args=(stop,), daemon=True, name="cs2wp-uploads").start()
        threading.Thread(target=ml_forever, daemon=True, name="cs2wp-ml").start()
    yield
    stop.set()


app = FastAPI(title="CS2 Win Probability", version="0.1.0", lifespan=lifespan)

# the web app when it is served from another origin (the Vite dev server)
ORIGINS = [o.strip() for o in os.environ.get(
    "CS2WP_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Content-Type"])


@app.get("/healthz")
def healthz():
    return {"ok": True, "storage": storage.store().kind, "bus": config.BUS, "db": db.engine().dialect.name}


# ---------------- demos & jobs ----------------
@app.get("/api/demos")
def demos():
    out = db.rows("SELECT * FROM demos ORDER BY created_at DESC")
    for d in out:
        d["score"] = json.loads(d["score"]) if d["score"] else None
    return out


@app.get("/api/status")
def status():
    """Health of the dataset, grouped by match: processed, scored by which model, Kalshi link + alignment."""
    demos = db.rows("SELECT * FROM demos ORDER BY created_at")
    matches: dict[str, dict] = {}
    for d in demos:
        k = match_key(d["id"])
        m = matches.setdefault(k, {"match": k, "maps": [], "first_seen": d["created_at"]})
        m["maps"].append({
            "id": d["id"], "map": d["map"], "status": d["status"], "rounds": d["n_rounds"],
            "kalshi": d["kalshi_status"], "ticker": d["kalshi_ticker"], "alignment": d["kalshi_confidence"],
            "scored_by": d["score_model"], "score_kind": d["score_kind"], "error": d["error"]})
    out = list(matches.values())
    allmaps = [x for m in out for x in m["maps"]]
    summary = {
        "matches": len(out), "maps": len(allmaps),
        "ready": sum(x["status"] == "ready" for x in allmaps),
        "failed": sum(x["status"] == "failed" for x in allmaps),
        "kalshi_linked": sum(x["kalshi"] == "linked" for x in allmaps),
        "kalshi_no_market": sum(x["kalshi"] == "no market" for x in allmaps),
        "alignment": {c: sum(x["alignment"] == c for x in allmaps) for c in ("good", "weak", "bad", "none")},
        "out_of_sample": sum(x["score_kind"] == "out-of-sample" for x in allmaps),
        "in_sample": sum(x["score_kind"] == "in-sample" for x in allmaps),
    }
    return clean({"summary": summary, "matches": sorted(out, key=lambda m: -(m["first_seen"] or 0))})


@app.get("/api/jobs")
def jobs():
    out = db.rows("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50")
    for j in out:
        j["payload"] = json.loads(j["payload"]) if j.get("payload") else None
    return out


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    r = db.rows("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not r:
        raise HTTPException(404)
    return r[0]


def _meta(demo_id: str) -> dict:
    p = storage.local_path(f"parsed/{demo_id}/meta.json")
    if not p.exists():
        raise HTTPException(404, "demo not parsed yet")
    return json.loads(p.read_text())


def _parquet(key: str, **kw) -> pd.DataFrame | None:
    p = storage.local_path(key)
    return pd.read_parquet(p, **kw) if p.exists() else None


@app.get("/api/demos/{demo_id}")
def demo(demo_id: str):
    meta = _meta(demo_id)
    s = _parquet(f"scores/{demo_id}.parquet")
    if s is not None:
        first = s.sort_values("tick").groupby("round").first()["p_ct"].to_dict()
        for r in meta["rounds"]:
            r["p_ct_start"] = first.get(r["round"])
    wp = storage.local_path(f"scores/{demo_id}_wpa.json")
    meta["wpa"] = json.loads(wp.read_text()) if wp.exists() else None
    if meta["wpa"] and not meta["wpa"].get("kind"):
        meta["wpa"]["kind"] = "out-of-sample" if str(meta["wpa"].get("model", "")).endswith(":cv") else "unknown"
    return clean(meta)


@app.get("/api/demos/{demo_id}/rounds/{round_no}")
def round_data(demo_id: str, round_no: int):
    """Everything the replay needs for one round at full tick rate, in columnar form."""
    meta = _meta(demo_id)
    r = next((x for x in meta["rounds"] if x["round"] == round_no), None)
    if r is None:
        raise HTTPException(404, "round not found")
    ticks = pd.read_parquet(storage.local_path(f"parsed/{demo_id}/ticks.parquet"), filters=[("round", "==", round_no)])
    tick_list = np.sort(ticks["tick"].unique())
    idx = {t: i for i, t in enumerate(tick_list)}
    n = len(tick_list)

    p_ct = [None] * n
    s = _parquet(f"scores/{demo_id}.parquet", filters=[("round", "==", round_no)])
    if s is not None:
        s = s.sort_values("tick")
        st, sv = s["tick"].to_numpy(), s["p_ct"].to_numpy()
        j = np.searchsorted(st, tick_list, side="right") - 1
        p_ct = [round(float(sv[k]), 4) if k >= 0 else None for k in j]
        p_ct = [None if v is None or np.isnan(v) else v for v in p_ct]

    players = []
    for sid, g in ticks.groupby("steamid"):
        g = g.sort_values("tick")
        pos = [idx[t] for t in g["tick"]]

        def col(series, fn, fill=None):
            arr = [fill] * n
            for i, v in zip(pos, series):
                arr[i] = fn(v)
            return arr

        def changes(series):
            out, last = [], object()
            for t, v in zip(g["tick"], series):
                v = None if (v is None or (isinstance(v, float) and np.isnan(v))) else v
                if v != last:
                    out.append([int(t), v])
                    last = v
            return out

        inv = g["inventory"].map(lambda x: list(x) if x is not None else [])
        players.append({
            "steamid": sid, "name": g["name"].iloc[0], "team": int(g["team_num"].iloc[0]),
            "x": col(g["X"], lambda v: round(float(v))), "y": col(g["Y"], lambda v: round(float(v))),
            "yaw": col(g["yaw"], lambda v: round(float(v)) if pd.notna(v) else 0),
            "hp": col(g["health"], lambda v: int(v) if pd.notna(v) else 0, 0),
            "alive": col(g["is_alive"], lambda v: 1 if v else 0, 0),
            "armor": changes(g["armor_value"].map(lambda v: int(v) if pd.notna(v) else 0)),
            "weapon": changes(g["active_weapon_name"]),
            "has_bomb": changes(inv.map(lambda x: "C4 Explosive" in x)),
            "money": changes(g["balance"].map(lambda v: int(v) if pd.notna(v) else 0)),
            "equip": changes(g["current_equip_value"].map(lambda v: int(v) if pd.notna(v) else 0)),
        })

    allev = pd.read_parquet(storage.local_path(f"parsed/{demo_id}/events.parquet"))
    ev = _parquet(f"scores/{demo_id}_events.parquet")
    ev = allev if ev is None else ev
    ev = ev[ev["round"] == round_no]
    keep = [c for c in ("tick", "type", "actor_name", "actor_steamid", "actor_team", "victim_name",
                        "victim_steamid", "victim_team", "weapon", "headshot", "x", "y",
                        "p_before", "p_after", "swing_ct") if c in ev]
    util = allev[(allev["round"] == round_no) & allev["type"].isin(["smoke", "molotov", "flash", "he"])]
    events = ev[keep].to_dict("records") + util[[c for c in keep if c in util]].to_dict("records")
    events.sort(key=lambda e: e["tick"])
    return clean({"round": r, "tickrate": TICKRATE, "ticks": tick_list.tolist(), "p_ct": p_ct,
                  "players": players, "events": events})


# ---------------- map background ----------------
@app.get("/api/maps/{map_name}")
def map_density(map_name: str):
    """Map outline drawn from where players have stood, plus bomb site markers from plants.
    Derived data: cached locally (CACHE), never uploaded."""
    demo_ids = [d["id"] for d in db.rows("SELECT id FROM demos WHERE map=? AND status='ready'", (map_name,))]
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"map_{map_name}.json"
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("n_demos") == len(demo_ids):
            return c
    xs, ys, plants = [], [], []
    for d in demo_ids[:30]:  # 30 maps already give a clean outline
        t = pd.read_parquet(storage.local_path(f"parsed/{d}/ticks.parquet"),
                            columns=["tick", "X", "Y", "is_alive", "last_place_name", "steamid"])
        a = t[t["is_alive"].fillna(False) & (t["tick"] % 8 == 0)]
        xs.append(a["X"].to_numpy())
        ys.append(a["Y"].to_numpy())
        e = pd.read_parquet(storage.local_path(f"parsed/{d}/events.parquet"))
        for pl in e[e["type"] == "plant"].itertuples():
            near = t[(t["steamid"] == pl.actor_steamid) & (t["tick"] <= pl.tick)].tail(1)
            place = near["last_place_name"].iloc[0] if len(near) else ""
            plants.append((pl.x, pl.y, place or ""))
    if not xs:
        raise HTTPException(404, "no demos for this map")
    x, y = np.concatenate(xs), np.concatenate(ys)
    pad = 300
    x0, x1, y0, y1 = x.min() - pad, x.max() + pad, y.min() - pad, y.max() + pad
    size = 256
    h, _, _ = np.histogram2d(y, x, bins=size, range=[[y0, y1], [x0, x1]])
    h = np.log1p(h)
    img = (255 * h / h.max()).astype(np.uint8) if h.max() > 0 else h.astype(np.uint8)
    sites: dict[str, list] = {}
    for px, py, place in plants:
        label = "A" if "A" in place.replace("Bombsite", "")[-1:] or place.endswith("A") else (
            "B" if place.endswith("B") else place or "?")
        sites.setdefault(label, []).append((px, py))
    out = {
        "map": map_name, "n_demos": len(demo_ids), "bounds": [float(x0), float(x1), float(y0), float(y1)],
        "size": size, "grid": base64.b64encode(img[::-1].tobytes()).decode(),  # row 0 = top (max y)
        "sites": {k: [float(np.mean([p[0] for p in v])), float(np.mean([p[1] for p in v]))] for k, v in sites.items()},
    }
    cache.write_text(json.dumps(out))
    return out


# ---------------- models ----------------
@app.get("/api/models")
def models():
    reg = modeling.registry()
    for v in reg["versions"]:
        mp = storage.local_path(f"models/{v}/metrics.json")
        if mp.exists():
            reg["versions"][v]["metrics"] = json.loads(mp.read_text())
    return clean(reg)


@app.post("/api/models/{version}/activate")
def activate(version: str):
    try:
        modeling.set_active(version)
    except KeyError:
        raise HTTPException(404, "unknown version") from None
    return {"active": version, "job_id": pjobs.enqueue("rescore")}


@app.get("/api/models/{version}/calibration.png")
def calibration(version: str):
    p = storage.local_path(f"models/{version}/calibration.png")
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


# ---------------- Kalshi comparison ----------------
@app.get("/api/demos/{demo_id}/kalshi")
def kalshi_compare(demo_id: str):
    from cs2wp_pipeline import kalshi
    c = kalshi.comparison(demo_id)
    if c is None:
        raise HTTPException(404, "no Kalshi market linked")
    return clean(c)


@app.get("/api/demos/{demo_id}/kalshi/analysis")
def kalshi_analysis(demo_id: str):
    from cs2wp_pipeline import kalshi
    a = kalshi.analysis(demo_id)
    if a is None:
        raise HTTPException(404, "no Kalshi market linked")
    return clean(a)


@app.get("/api/demos/{demo_id}/kalshi/rounds/{round_no}")
def kalshi_round(demo_id: str, round_no: int):
    """Trade-by-trade Kalshi prices during one round, on the demo tick axis."""
    from cs2wp_pipeline import kalshi
    t = kalshi.round_trades(demo_id, round_no)
    if t is None:
        raise HTTPException(404, "no Kalshi market linked")
    return clean(t)


@app.get("/api/demos/{demo_id}/mapwin")
def mapwin_series(demo_id: str, every: int = 64, round_no: int | None = Query(None, alias="round")):
    """Map win probability for team A (1 point per second by default; one round at full rate)."""
    s = _parquet(f"scores/{demo_id}.parquet", columns=["round", "tick", "p_map_a"])
    if s is None:
        raise HTTPException(404, "demo not scored yet")
    if round_no is not None:
        s = s[s["round"] == round_no]
    s = s.iloc[::max(1, every)]
    return clean({"teams": _meta(demo_id).get("teams"), "tick": s["tick"].tolist(),
                  "round": s["round"].tolist(), "p_map_a": [round(float(x), 4) for x in s["p_map_a"]]})


# ---------------- live path ----------------
@app.websocket("/ws/live/{demo_id}/{round_no}")
async def live_ws(ws: WebSocket, demo_id: str, round_no: int):
    await live.serve(ws, demo_id, round_no)


# ---------------- optional static UI (built cs2wp-web) ----------------
_dist = os.environ.get("CS2WP_WEB_DIST")
if _dist and Path(_dist, "index.html").exists():
    @app.get("/")
    def index():
        return RedirectResponse("/app/")

    app.mount("/app", StaticFiles(directory=_dist, html=True), name="web")


__all__ = ["app", "WebSocketDisconnect"]
