"""Parse a demo with demoparser2 into rounds, per-tick player state (64 Hz) and a unified event table."""

import json
import os
import threading

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from cs2wp_core import storage
from cs2wp_core.config import CT, PARSE_EVERY, PARSED, POST_ROUND_TICKS, TICKRATE, VALID_REASONS, T

TICK_FIELDS = [
    "X", "Y", "Z", "yaw", "is_alive", "health", "armor_value", "has_helmet", "has_defuser",
    "team_num", "current_equip_value", "balance", "inventory", "active_weapon_name",
    "is_defusing", "flash_duration", "is_bomb_planted", "is_bomb_dropped", "in_bomb_zone",
    "last_place_name", "game_time", "round_start_time",
]

# event name -> (type, actor prefix)
SIMPLE_EVENTS = {
    "bomb_planted": "plant", "bomb_begindefuse": "defuse_start", "bomb_defused": "defuse",
    "bomb_exploded": "explode", "bomb_dropped": "bomb_drop", "bomb_pickup": "bomb_pickup",
    "smokegrenade_detonate": "smoke", "inferno_startburn": "molotov",
    "flashbang_detonate": "flash", "hegrenade_detonate": "he",
}


def _event(p, name, **kw):
    """parse_event, but always a DataFrame (demoparser2 returns [] for events a demo lacks)."""
    try:
        r = p.parse_event(name, **kw)
    except Exception:
        return pd.DataFrame()
    return r if isinstance(r, pd.DataFrame) else pd.DataFrame(r)


# Newer demos give round_end winner/reason as names instead of numbers.
WINNER_NAMES = {"t": T, "terrorist": T, "terrorists": T, "ct": CT, "counter-terrorist": CT, "cts": CT}
REASON_NAMES = {"bomb_exploded": 1, "target_bombed": 1, "bomb_defused": 7, "t_killed": 8,
                "terrorists_killed": 8, "ct_killed": 9, "cts_killed": 9, "time_ran_out": 12,
                "target_saved": 12}


def _winner(v) -> int:
    if pd.isna(v):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return WINNER_NAMES.get(str(v).strip().lower(), 0)


def _reason(v) -> int:
    if pd.isna(v):
        return -1
    try:
        return int(v)
    except (TypeError, ValueError):
        return REASON_NAMES.get(str(v).strip().lower(), -1)  # surrenders etc. -> invalid


def _rounds(p):
    ends = _event(p, "round_end")
    freezes = _event(p, "round_freeze_end")
    starts = pd.concat([_event(p, "round_announce_match_start"), _event(p, "begin_new_match")])
    match_start = int(starts["tick"].max()) if len(starts) else 0
    freeze_ticks = np.sort(freezes["tick"].to_numpy()) if len(freezes) else np.array([], int)

    rounds, prev_end = [], 0
    for _, r in ends.sort_values("tick").iterrows():
        end = int(r["tick"])
        cand = freeze_ticks[(freeze_ticks > prev_end) & (freeze_ticks < end)]
        prev_end = end
        if not len(cand):
            continue
        freeze = int(cand[-1])
        winner = _winner(r["winner"])
        reason = _reason(r["reason"])
        rounds.append({
            "freeze_end": freeze, "end": end, "winner": winner, "reason": reason,
            "valid": bool(reason in VALID_REASONS and winner in (CT, T) and freeze >= match_start),
        })
    for i, r in enumerate(rounds, 1):
        r["round"] = i
    # CT/T team names flip at half time, so store per round from the tick data later
    return rounds


def _events(p):
    frames = []
    k = _event(p, "player_death", player=["team_num"], other=[])
    if len(k):
        frames.append(pd.DataFrame({
            "tick": k["tick"], "type": "kill",
            "actor_name": k.get("attacker_name"), "actor_steamid": k.get("attacker_steamid"),
            "actor_team": k.get("attacker_team_num"),
            "victim_name": k.get("user_name"), "victim_steamid": k.get("user_steamid"),
            "victim_team": k.get("user_team_num"),
            "assister_name": k.get("assister_name"), "weapon": k.get("weapon"),
            "headshot": k.get("headshot"),
        }))
    for name, typ in SIMPLE_EVENTS.items():
        e = _event(p, name, player=["X", "Y", "team_num"])
        if not len(e):
            continue
        frames.append(pd.DataFrame({
            "tick": e["tick"], "type": typ,
            "actor_name": e.get("user_name"), "actor_steamid": e.get("user_steamid"),
            "actor_team": e.get("user_team_num"),
            "x": e["x"] if "x" in e else e.get("user_X"),
            "y": e["y"] if "y" in e else e.get("user_Y"),
            "site": e.get("site"),
        }))
    ev = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["tick", "type"])
    for c in ("actor_steamid", "victim_steamid"):
        if c in ev:
            ev[c] = ev[c].astype("string")
    return ev.sort_values("tick", kind="stable").reset_index(drop=True)


def _assign_round(ticks: np.ndarray, rounds) -> np.ndarray:
    out = np.zeros(len(ticks), dtype=np.int32)
    for r in rounds:
        m = (ticks >= r["freeze_end"]) & (ticks <= r["end"] + POST_ROUND_TICKS)
        out[m] = r["round"]
    return out


def parse_demo(demo_id: str) -> dict:
    p = DemoParser(str(storage.local_path(f"raw/{demo_id}.dem")))
    header = p.parse_header()
    rounds = _rounds(p)
    if not rounds:
        raise ValueError("no complete rounds found in demo")

    wanted = sorted({t for r in rounds
                     for t in range(r["freeze_end"], r["end"] + POST_ROUND_TICKS + 1, PARSE_EVERY)})
    ticks = p.parse_ticks(TICK_FIELDS, ticks=wanted)
    ticks = ticks[ticks["team_num"].isin([CT, T])].copy()
    ticks["steamid"] = ticks["steamid"].astype("string")
    ticks["round"] = _assign_round(ticks["tick"].to_numpy(), rounds)
    ticks = ticks[ticks["round"] > 0]

    # knife rounds: nobody holds a firearm when the round goes live
    knives_only = lambda inv: all(  # noqa: E731
        ("knife" in w.lower() or "bayonet" in w.lower() or w in ("C4 Explosive", "Zeus x27"))
        for w in (inv if inv is not None else []))
    for r in rounds:
        first_tick = ticks.loc[ticks["round"] == r["round"], "tick"].min()
        at = ticks[(ticks["round"] == r["round"]) & (ticks["tick"] == first_tick)]
        if len(at) and at["inventory"].map(knives_only).all():
            r["valid"] = False
            r["knife_round"] = True

    events = _events(p)
    events["round"] = _assign_round(events["tick"].to_numpy(), rounds)
    # game clock at each event (stops during pauses), so timers never need the tick table
    clock = ticks.groupby("tick")["game_time"].max()
    events["game_time"] = events["tick"].map(clock)
    events = events[events["round"] > 0].reset_index(drop=True)

    # players and per-round side assignment (teams swap at half)
    first = ticks.sort_values("tick").groupby(["round", "steamid"]).first().reset_index()
    players = (ticks.groupby("steamid")["name"].agg(lambda s: s.mode().iat[0]).reset_index()
               .to_dict("records"))
    for r in rounds:
        fr = first[first["round"] == r["round"]]
        r["ct_players"] = fr.loc[fr["team_num"] == CT, "steamid"].tolist()
        r["t_players"] = fr.loc[fr["team_num"] == T, "steamid"].tolist()

    # Team A = the side that was CT in round 1; follow it through side swaps by player overlap.
    team_a = set(rounds[0]["ct_players"])
    for r in rounds:
        r["a_is_ct"] = len(team_a & set(r["ct_players"])) >= len(team_a & set(r["t_players"]))

    # Team names + the real team scores at each freeze end (scores follow teams, not sides).
    side_info = {}
    try:
        tt = p.parse_ticks(["team_clan_name", "team_rounds_total", "team_num"],
                           ticks=[r["freeze_end"] for r in rounds])
        for (tick, team), g in tt.groupby(["tick", "team_num"]):
            side_info[(int(tick), int(team))] = (g["team_clan_name"].dropna().iloc[0] if g["team_clan_name"].notna().any() else None,
                                                 int(g["team_rounds_total"].max()) if g["team_rounds_total"].notna().any() else None)
    except Exception:
        pass
    a_score = b_score = 0
    a_names, b_names = [], []
    for r in rounds:
        a_side, b_side = (CT, T) if r["a_is_ct"] else (T, CT)
        na, sa = side_info.get((r["freeze_end"], a_side), (None, None))
        nb, sb = side_info.get((r["freeze_end"], b_side), (None, None))
        if sa is not None and sb is not None:   # trust the game's own score
            a_score, b_score = sa, sb
        r["a_score"], r["b_score"] = a_score, b_score
        r["ct_score"], r["t_score"] = (a_score, b_score) if r["a_is_ct"] else (b_score, a_score)
        a_names.append(na)
        b_names.append(nb)
        a_won = (r["winner"] == CT) == r["a_is_ct"] and r["winner"] in (CT, T)
        if r["winner"] in (CT, T):  # fallback count for the next round
            a_score, b_score = (a_score + 1, b_score) if a_won else (a_score, b_score + 1)
    mode = lambda xs, d: pd.Series([x for x in xs if x]).mode().iat[0] if any(xs) else d  # noqa: E731
    teams = {"a": {"name": mode(a_names, "Team A"), "steamids": sorted(team_a)},
             "b": {"name": mode(b_names, "Team B"),
                   "steamids": sorted(set(ticks["steamid"].unique()) - team_a)}}

    out = PARSED / demo_id
    out.mkdir(parents=True, exist_ok=True)
    ticks.to_parquet(out / "ticks.parquet", index=False)
    events.to_parquet(out / "events.parquet", index=False)
    # same match from a different file (re-download, truncated copy) -> same fingerprint
    import hashlib
    fp_src = "|".join([header.get("map_name", ""), ",".join(sorted(ticks["steamid"].dropna().unique())),
                       ",".join(str(r["end"] - rounds[0]["freeze_end"]) for r in rounds[:3])])
    meta = {
        "demo_id": demo_id, "map": header.get("map_name", "unknown"),
        "fingerprint": hashlib.sha1(fp_src.encode()).hexdigest()[:16],
        "server": header.get("server_name"), "tickrate": TICKRATE,
        "players": players, "rounds": rounds, "teams": teams,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    publish_parsed(demo_id)
    return meta


def load(demo_id: str):
    meta = load_meta(demo_id)
    return (meta, pd.read_parquet(storage.local_path(f"parsed/{demo_id}/ticks.parquet")),
            pd.read_parquet(storage.local_path(f"parsed/{demo_id}/events.parquet")))


def load_meta(demo_id: str) -> dict:
    return json.loads(storage.local_path(f"parsed/{demo_id}/meta.json").read_text())


def save_meta(demo_id: str, meta: dict) -> None:
    p = storage.local_path(f"parsed/{demo_id}/meta.json", fetch=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=1, default=str))
    storage.publish(f"parsed/{demo_id}/meta.json")


def publish_parsed(demo_id: str) -> None:
    storage.publish(*(f"parsed/{demo_id}/{f}" for f in ("ticks.parquet", "events.parquet", "meta.json")))


# Parsing a full map peaks around 2.3 GB of memory. Worker threads would otherwise parse several
# maps at once and get killed for running out of memory (seen on a 6 GB Docker VM; the AWS stage-1
# host has 8 GB), so parses take turns. Raise it on big machines.
_PARSE_SLOTS = threading.BoundedSemaphore(int(os.environ.get("CS2WP_PARSE_CONCURRENCY", "1")))


def parse_isolated(demo_id: str, timeout: int = 900) -> dict:
    """Run parse_demo in a child process: a Rust panic or crash in demoparser2 on a corrupt
    demo then fails only this job instead of taking down the server."""
    with _PARSE_SLOTS:
        return _parse_isolated(demo_id, timeout)


def _parse_isolated(demo_id: str, timeout: int) -> dict:
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "cs2wp_pipeline.parse", demo_id],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        msg = (r.stderr.strip().splitlines() or ["parser crashed"])[-1]
        raise ValueError(f"could not parse demo (corrupt or unsupported): {msg[:300]}")
    return load_meta(demo_id)


if __name__ == "__main__":
    import sys

    parse_demo(sys.argv[1])
