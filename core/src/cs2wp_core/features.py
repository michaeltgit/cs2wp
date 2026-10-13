"""Shared feature library: player ticks -> one row per snapshot tick with CT/T aggregates.

Used unchanged by training, batch scoring and the live replay path. A feature at tick t only
uses data at or before t (no peeking at later events), so it behaves the same live.
"""

import numpy as np
import pandas as pd

from . import sites
from .config import BOMB_TIME, CT, ROUND_TIME, TICKRATE, T

SITES = sites.load()

RIFLES = {"AK-47", "M4A4", "M4A1-S", "Galil AR", "FAMAS", "SG 553", "AUG"}
AWPS = {"AWP"}
SNIPERS_OTHER = {"SSG 08", "SCAR-20", "G3SG1"}
SMGS = {"MAC-10", "MP9", "MP7", "MP5-SD", "UMP-45", "P90", "PP-Bizon"}
HEAVY = {"Nova", "XM1014", "Sawed-Off", "MAG-7", "M249", "Negev"}
SMOKES = {"Smoke Grenade"}
FLASHES = {"Flashbang"}
MOLOS = {"Molotov", "Incendiary Grenade"}
HES = {"High Explosive Grenade"}
C4 = "C4 Explosive"

INV_COLS = ["rifle", "awp", "scout", "smg", "heavy", "smokes", "flashes", "molos", "hes", "has_c4"]
_inv_cache: dict[tuple, tuple] = {}


def _inv_counts(inv) -> tuple:
    key = tuple(inv) if inv is not None else ()
    hit = _inv_cache.get(key)
    if hit is None:
        s = list(key)
        hit = (
            int(any(w in RIFLES for w in s)), int(any(w in AWPS for w in s)),
            int(any(w in SNIPERS_OTHER for w in s)), int(any(w in SMGS for w in s)),
            int(any(w in HEAVY for w in s)),
            sum(w in SMOKES for w in s), sum(w in FLASHES for w in s),
            sum(w in MOLOS for w in s), sum(w in HES for w in s), int(C4 in s),
        )
        _inv_cache[key] = hit
    return hit


FEATURES = [
    "ct_alive", "t_alive", "alive_diff",
    "ct_hp", "t_hp", "ct_armor", "t_armor", "ct_helmets", "t_helmets",
    "ct_equip", "t_equip", "equip_diff", "ct_money", "t_money",
    "ct_kits", "ct_rifle", "t_rifle", "ct_awp", "t_awp", "ct_scout", "t_scout",
    "ct_smg", "t_smg", "ct_heavy", "t_heavy",
    "ct_smokes", "t_smokes", "ct_flashes", "t_flashes", "ct_molos", "t_molos", "ct_hes", "t_hes",
    "round_time_left", "bomb_planted", "bomb_time_left", "defusing", "defusing_with_kit",
    "bomb_dropped", "t_carrier_alive", "carrier_in_zone", "t_in_zone",
    "ct_min_dist_bomb", "ct_near_bomb", "t_near_bomb",
    "t_min_dist_site", "ct_min_dist_site", "carrier_dist_site",
    "secs_since_kill", "round_num", "ct_score", "t_score", "score_diff", "map",
    # v012: what a viewer would call important and the parser already gives us
    "ct_blind", "t_blind",                                  # players blind right now
    "ct_smokes_up", "t_smokes_up", "ct_molos_up", "t_molos_up",  # utility in effect right now
    "smoke_on_bomb", "molo_on_bomb",                        # ... covering the planted bomb
    "ct_on_a", "ct_on_b", "t_on_a", "t_on_b",               # players on each bomb site
    "ct_max_hp", "t_max_hp", "ct_best_equip", "t_best_equip",  # strongest player still alive
    "ct_recent_kills", "t_recent_kills",                    # kills in the last few seconds
]
SMOKE_SECS, MOLO_SECS, KILL_SECS = 18.0, 7.0, 5.0  # CS2: smoke ~18 s, molotov ~7 s; fights/trades window
ON_BOMB_SMOKE, ON_BOMB_MOLO = 250.0, 200.0          # units from the planted bomb that count as covering it
CATEGORICAL = ["map"]


def _round_context(meta, events):
    """Per round: freeze tick, first plant tick + bomb position, kill ticks."""
    ctx = {}
    for r in meta["rounds"]:
        ev = events[events["round"] == r["round"]]
        plant = ev[ev["type"] == "plant"]
        ctx[r["round"]] = {
            **r,
            "plant_tick": int(plant["tick"].iloc[0]) if len(plant) else None,
            "plant_gt": float(plant["game_time"].iloc[0]) if len(plant) and "game_time" in plant
                        and pd.notna(plant["game_time"].iloc[0]) else None,
            "bomb_xy": (float(plant["x"].iloc[0]), float(plant["y"].iloc[0])) if len(plant) else None,
            "kill_ticks": np.sort(ev.loc[ev["type"] == "kill", "tick"].to_numpy()),
        }
    return ctx


def _event_windows(ctx, events, rounds, ticks) -> dict[str, np.ndarray]:
    """Counts of recent events per side at each (round, tick), using only events up to that tick:
    smokes / molotovs still in effect, kills in the last few seconds, and whether an active smoke or
    molotov covers the planted bomb."""
    n = len(ticks)
    out = {k: np.zeros(n, dtype=np.int16) for k in
           ("ct_smokes_up", "t_smokes_up", "ct_molos_up", "t_molos_up", "ct_recent_kills", "t_recent_kills",
            "smoke_on_bomb", "molo_on_bomb")}
    if events is None or events.empty or not {"actor_team", "x", "y"} <= set(events.columns):
        return out
    spec = [("smoke", SMOKE_SECS, "smokes_up"), ("molotov", MOLO_SECS, "molos_up"), ("kill", KILL_SECS, "recent_kills")]
    for rnd in np.unique(rounds):
        idx = np.flatnonzero(rounds == rnd)
        tt = ticks[idx]
        ev = events[events["round"] == rnd]
        for etype, secs, name in spec:
            e = ev[ev["type"] == etype]
            for side, pre in ((CT, "ct"), (T, "t")):
                et = np.sort(e.loc[e["actor_team"] == side, "tick"].to_numpy())
                if et.size:
                    out[f"{pre}_{name}"][idx] = (np.searchsorted(et, tt, side="right")
                                                 - np.searchsorted(et, tt - secs * TICKRATE, side="right"))
        c = ctx.get(rnd) or {}
        if c.get("bomb_xy") and c.get("plant_tick") is not None:
            bx, by = c["bomb_xy"]
            for etype, secs, radius, name in (("smoke", SMOKE_SECS, ON_BOMB_SMOKE, "smoke_on_bomb"),
                                              ("molotov", MOLO_SECS, ON_BOMB_MOLO, "molo_on_bomb")):
                e = ev[ev["type"] == etype]
                near = e[np.hypot(e["x"].astype(float) - bx, e["y"].astype(float) - by) < radius]
                for t0 in near["tick"].to_numpy():
                    on = (tt >= t0) & (tt < t0 + secs * TICKRATE) & (tt >= c["plant_tick"])
                    out[name][idx] = np.maximum(out[name][idx], on.astype(np.int16))
    return out


def signed(df: pd.DataFrame) -> pd.DataFrame:
    """Same arithmetic in batch and live (both caught by the live == batch validation gate):
    * unsigned ints -> int64: demoparser2 writes some columns as uint32 (equipment value, team), so
      CT - T equipment wrapped around to ~4.3e9 whenever T had more;
    * float32 -> float64: live frames arrive through JSON as float64, so distances computed from
      float32 positions in batch differed in the 4th decimal."""
    cols = {c: "int64" for c, d in df.dtypes.items() if pd.api.types.is_unsigned_integer_dtype(d)}
    cols |= {c: "float64" for c, d in df.dtypes.items() if d == "float32"}
    return df.astype(cols) if cols else df


def build(meta: dict, ticks: pd.DataFrame, events: pd.DataFrame, every: int = 1) -> pd.DataFrame:
    """One row per (round, tick) from freeze end to round end, sampled every `every` ticks."""
    ticks, events = signed(ticks), signed(events)
    ctx = _round_context(meta, events)
    bounds = pd.DataFrame([{"round": k, "freeze_end": v["freeze_end"], "end": v["end"]}
                           for k, v in ctx.items()])
    df = ticks.merge(bounds, on="round")
    df = df[(df["tick"] >= df["freeze_end"]) & (df["tick"] <= df["end"])]
    if every > 1:
        df = df[(df["tick"] - df["freeze_end"]) % every == 0]
    if df.empty:
        return pd.DataFrame(columns=["demo_id", "round", "tick", *FEATURES, "ct_win", "valid"])

    alive = (df["is_alive"].fillna(False).astype(bool) & (df["health"].fillna(0) > 0)).to_numpy()
    inv = np.array([_inv_counts(x) for x in df["inventory"].to_numpy()], dtype=np.int16).reshape(-1, len(INV_COLS))
    inv_df = pd.DataFrame(inv, columns=INV_COLS, index=df.index)

    a = pd.DataFrame({
        "round": df["round"], "tick": df["tick"], "side": df["team_num"],
        "alive": alive.astype(np.int8),
        "hp": df["health"].fillna(0) * alive,
        "armor": df["armor_value"].fillna(0) * alive,
        "helmet": df["has_helmet"].fillna(False).astype(int) * alive,
        "equip": df["current_equip_value"].fillna(0) * alive,
        "money": df["balance"].fillna(0),
        "kit": df["has_defuser"].fillna(False).astype(int) * alive,
        "defusing": df["is_defusing"].fillna(False).astype(int) * alive,
        "in_zone": df["in_bomb_zone"].fillna(False).astype(int) * alive,
        **{c: inv_df[c] * alive for c in INV_COLS},
    }, index=df.index)
    # blind right now: flash_duration is > 0 only while the player is flashed
    a["blind"] = ((df["flash_duration"].fillna(0) > 0).astype(int) * alive) if "flash_duration" in df else 0
    # on a bomb site: the game's zone names, BombsiteA / BombsiteB on every map we have (works on Nuke,
    # where A and B are stacked vertically). in_bomb_zone can't be used: the demo only sets it for the
    # bomb carrier.
    place = df["last_place_name"].fillna("").astype(str) if "last_place_name" in df else pd.Series("", index=df.index)
    a["on_a"] = (place == "BombsiteA").astype(int).to_numpy() * alive
    a["on_b"] = (place == "BombsiteB").astype(int).to_numpy() * alive
    a["carrier_in_zone"] = a["has_c4"] * a["in_zone"]
    a["defuse_kit"] = a["defusing"] * a["kit"]

    # distance to the planted bomb (only once it is planted)
    bx = df["round"].map(lambda r: ctx[r]["bomb_xy"][0] if ctx[r]["bomb_xy"] else np.nan)
    by = df["round"].map(lambda r: ctx[r]["bomb_xy"][1] if ctx[r]["bomb_xy"] else np.nan)
    ptick = df["round"].map(lambda r: ctx[r]["plant_tick"] if ctx[r]["plant_tick"] is not None else np.inf)
    planted_now = (df["tick"] >= ptick).to_numpy()
    dist = np.hypot(df["X"] - bx, df["Y"] - by).to_numpy()
    dist = np.where(planted_now & alive, dist, np.nan)
    a["dist_bomb"] = dist
    a["near_bomb"] = (dist < 1000).astype(int)

    site_xy = [v[:2] for v in SITES.get(meta["map"], {}).values()]
    if site_xy:
        d_site = np.min([np.hypot(df["X"].to_numpy() - sx, df["Y"].to_numpy() - sy) for sx, sy in site_xy], axis=0)
        d_site = np.where(alive, d_site, np.nan)
    else:
        d_site = np.full(len(df), np.nan)
    a["dist_site"] = d_site
    a["carrier_dist_site"] = np.where(a["has_c4"].to_numpy() > 0, d_site, np.nan)

    g = a.groupby(["round", "tick", "side"])
    agg = g.agg(alive=("alive", "sum"), hp=("hp", "sum"), armor=("armor", "sum"),
                helmets=("helmet", "sum"), equip=("equip", "sum"), money=("money", "sum"),
                kits=("kit", "sum"), defusing=("defusing", "sum"), defuse_kit=("defuse_kit", "sum"),
                in_zone=("in_zone", "sum"), carrier=("has_c4", "sum"),
                carrier_in_zone=("carrier_in_zone", "sum"),
                rifle=("rifle", "sum"), awp=("awp", "sum"), scout=("scout", "sum"),
                smg=("smg", "sum"), heavy=("heavy", "sum"), smokes=("smokes", "sum"),
                flashes=("flashes", "sum"), molos=("molos", "sum"), hes=("hes", "sum"),
                min_dist=("dist_bomb", "min"), near=("near_bomb", "sum"),
                min_site=("dist_site", "min"), carrier_site=("carrier_dist_site", "min"),
                blind=("blind", "sum"), on_a=("on_a", "sum"), on_b=("on_b", "sum"),
                max_hp=("hp", "max"), best_equip=("equip", "max")).unstack("side")
    agg.columns = [f"{'ct' if side == CT else 't'}_{name}" for name, side in agg.columns]
    agg = agg.reset_index()
    for c in [f"{s}_{n}" for s in ("ct", "t") for n in
              ("alive", "hp", "armor", "helmets", "equip", "money", "kits", "defusing", "defuse_kit",
               "in_zone", "carrier", "carrier_in_zone", "rifle", "awp", "scout", "smg", "heavy",
               "smokes", "flashes", "molos", "hes", "near", "blind", "on_a", "on_b", "max_hp", "best_equip")]:
        if c not in agg:
            agg[c] = 0
    for c in ("ct_min_dist", "t_min_dist", "ct_min_site", "t_min_site", "t_carrier_site"):
        if c not in agg:
            agg[c] = np.nan

    # game-state flags from any player row of that tick
    gs = df.groupby(["round", "tick"]).agg(bomb_dropped=("is_bomb_dropped", "max")).reset_index()
    out = agg.merge(gs, on=["round", "tick"], how="left")

    r = out["round"]
    freeze = r.map(lambda k: ctx[k]["freeze_end"])
    plant = r.map(lambda k: ctx[k]["plant_tick"] if ctx[k]["plant_tick"] is not None else np.inf)
    planted = out["tick"] >= plant
    secs = (out["tick"] - freeze) / TICKRATE
    bomb_secs = (out["tick"] - plant) / TICKRATE
    # Prefer the game's own clock: it stops during pauses, tick counts do not.
    if {"game_time", "round_start_time"} <= set(df.columns):
        clock = df.groupby(["round", "tick"]).agg(gt=("game_time", "max"), rst=("round_start_time", "max")).reset_index()
        clock = out[["round", "tick"]].merge(clock, on=["round", "tick"], how="left")
        game_secs = (clock["gt"] - clock["rst"]).to_numpy()
        secs = np.where(np.isfinite(game_secs) & (game_secs >= 0), game_secs, secs)
        plant_gt = {k: c["plant_gt"] for k, c in ctx.items() if c.get("plant_gt") is not None}
        pg = r.map(lambda k: plant_gt.get(k, np.nan)).to_numpy()
        live_bomb = clock["gt"].to_numpy() - pg
        bomb_secs = np.where(np.isfinite(live_bomb), live_bomb, bomb_secs)
    last_kill = np.array([
        (kt[np.searchsorted(kt, t, side="right") - 1] if (kt := ctx[k]["kill_ticks"]).size
         and np.searchsorted(kt, t, side="right") > 0 else ctx[k]["freeze_end"])
        for k, t in zip(r.to_numpy(), out["tick"].to_numpy())])

    win = _event_windows(ctx, events, r.to_numpy(), out["tick"].to_numpy())

    feats = pd.DataFrame({
        "demo_id": meta["demo_id"], "round": r, "tick": out["tick"],
        "ct_alive": out["ct_alive"], "t_alive": out["t_alive"],
        "alive_diff": out["ct_alive"] - out["t_alive"],
        "ct_hp": out["ct_hp"], "t_hp": out["t_hp"],
        "ct_armor": out["ct_armor"], "t_armor": out["t_armor"],
        "ct_helmets": out["ct_helmets"], "t_helmets": out["t_helmets"],
        "ct_equip": out["ct_equip"], "t_equip": out["t_equip"],
        "equip_diff": out["ct_equip"] - out["t_equip"],
        "ct_money": out["ct_money"], "t_money": out["t_money"],
        "ct_kits": out["ct_kits"],
        **{f"{s}_{w}": out[f"{s}_{w}"] for w in ("rifle", "awp", "scout", "smg", "heavy",
                                                  "smokes", "flashes", "molos", "hes")
           for s in ("ct", "t")},
        "round_time_left": np.clip(ROUND_TIME - secs, 0, None),
        "bomb_planted": planted.astype(int),
        "bomb_time_left": np.where(planted, np.clip(BOMB_TIME - bomb_secs, 0, None), 0.0),
        "defusing": (out["ct_defusing"] > 0).astype(int),
        "defusing_with_kit": (out["ct_defuse_kit"] > 0).astype(int),
        "bomb_dropped": out["bomb_dropped"].fillna(False).astype(int),
        "t_carrier_alive": (out["t_carrier"] > 0).astype(int),
        "carrier_in_zone": (out["t_carrier_in_zone"] > 0).astype(int),
        "t_in_zone": out["t_in_zone"],
        "ct_min_dist_bomb": out["ct_min_dist"], "ct_near_bomb": out["ct_near"],
        "t_near_bomb": out["t_near"],
        "t_min_dist_site": out["t_min_site"], "ct_min_dist_site": out["ct_min_site"],
        "carrier_dist_site": out["t_carrier_site"],
        "secs_since_kill": (out["tick"] - last_kill) / TICKRATE,
        "round_num": r,
        "ct_score": r.map(lambda k: ctx[k]["ct_score"]), "t_score": r.map(lambda k: ctx[k]["t_score"]),
        "map": meta["map"],
        "ct_blind": out["ct_blind"], "t_blind": out["t_blind"],
        "ct_on_a": out["ct_on_a"], "ct_on_b": out["ct_on_b"], "t_on_a": out["t_on_a"], "t_on_b": out["t_on_b"],
        "ct_max_hp": out["ct_max_hp"], "t_max_hp": out["t_max_hp"],
        "ct_best_equip": out["ct_best_equip"], "t_best_equip": out["t_best_equip"],
        **win,
    })
    feats["score_diff"] = feats["ct_score"] - feats["t_score"]
    feats["ct_win"] = r.map(lambda k: int(ctx[k]["winner"] == CT))
    feats["valid"] = r.map(lambda k: ctx[k]["valid"])
    return feats[["demo_id", "round", "tick", *FEATURES, "ct_win", "valid"]].reset_index(drop=True)
