"""Kalshi CS2 map markets: find the market for a demo, pull 1-minute prices, align them to demo ticks.

Uses only public (unauthenticated) endpoints. Kalshi prices "team X wins map N", so we compare
against our map win probability (mapwin.py), not the round probability.

Kalshi moves settled markets and old trades to separate ``/historical/...`` endpoints once they
are older than a rolling cutoff (``/historical/cutoff``, a few months). Every lookup here checks
both, so matches from before the cutoff link like recent ones.
"""

import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime

import certifi
import numpy as np
import pandas as pd

from cs2wp_core import mapwin, storage
from cs2wp_core.config import CACHE, KALSHI, TICKRATE

from .parse import load_meta

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = ("KXCS2MAP",)
LINKS = KALSHI  # local cache dir for kalshi/<demo_id>.json, _candles.parquet, _trades.parquet


def link_info(demo_id: str) -> dict | None:
    """The linked market for a demo (None if not linked)."""
    key = f"kalshi/{demo_id}.json"
    if not storage.exists(key):
        return None
    return json.loads(storage.local_path(key).read_text())
_SSL = ssl.create_default_context(cafile=certifi.where())


def _get(path, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cs2-winprob"}), timeout=20, context=_SSL) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def _ts(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


_CUTOFF: dict = {}


def cutoff() -> dict[str, int]:
    """Kalshi's historical cutoff (unix s): markets settled before ``settled`` and trades created
    before ``trades`` are only served by the /historical endpoints. Cached for an hour."""
    if _CUTOFF.get("at", 0) < time.time() - 3600:
        try:
            d = _get("/historical/cutoff")
            _CUTOFF.update(settled=_ts(d["market_settled_ts"]), trades=_ts(d["trades_created_ts"]), at=time.time())
        except (OSError, KeyError, ValueError):
            if "settled" not in _CUTOFF:
                return {"settled": 0, "trades": 0}  # unreachable: behave as before (live endpoints only)
    return {"settled": _CUTOFF["settled"], "trades": _CUTOFF["trades"]}


def _historical_markets(series: str, max_age: float = 86400) -> list[dict]:
    """Every settled market of a series on the historical endpoint (~14 requests for KXCS2MAP),
    cached on disk for a day: it only grows when the cutoff moves forward."""
    path = CACHE / f"kalshi_historical_{series}.json"
    if path.exists() and path.stat().st_mtime > time.time() - max_age:
        return json.loads(path.read_text())
    out, cursor = [], None
    while True:
        d = _get("/historical/markets", series_ticker=series, limit=1000, cursor=cursor)
        out += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def _market_row(m: dict, series: str, historical: bool) -> dict:
    return {"ticker": m["ticker"], "series": series, "title": m.get("title"),
            "yes_team": m.get("yes_sub_title"), "status": m.get("status"),
            "result": m.get("result"), "open_time": m.get("open_time"),
            "close_time": m.get("close_time"),
            "volume": float(m.get("volume_fp") or m.get("volume") or 0),
            "rules": m.get("rules_primary", ""), "historical": historical}


def search_markets(query: str = "", days: int = 30, limit: int = 200) -> list[dict]:
    """CS2 map markets whose title mentions `query` (team name), most recent first. Includes
    markets already moved to Kalshi's historical endpoints when the window reaches back that far."""
    now = int(time.time())
    since = now - days * 86400
    out, q = [], query.lower().strip()

    def match(m):
        title = f"{m.get('title', '')} {m.get('yes_sub_title', '')} {m.get('rules_primary', '')}"
        return not q or all(part in title.lower() for part in q.split())

    for series in SERIES:
        cursor = None
        while True:
            d = _get("/markets", series_ticker=series, limit=1000, cursor=cursor, min_close_ts=since)
            out += [_market_row(m, series, False) for m in d.get("markets", []) if match(m)]
            cursor = d.get("cursor")
            if not cursor or len(out) >= limit:
                break
        if since < cutoff()["settled"]:
            seen = {m["ticker"] for m in out}
            out += [_market_row(m, series, True) for m in _historical_markets(series)
                    if m["ticker"] not in seen and m.get("close_time") and _ts(m["close_time"]) >= since and match(m)]
    return sorted(out, key=lambda m: m["close_time"] or "", reverse=True)[:limit]


_POOL: dict = {}


def _all_markets(days: int) -> list[dict]:
    """All CS2 map markets that closed in the last `days` (live + historical), cached for 10 minutes
    so linking many maps in a row lists them once."""
    if _POOL.get("days") != days or _POOL.get("at", 0) < time.time() - 600:
        _POOL.update(days=days, at=time.time(), markets=search_markets("", days=days, limit=1_000_000))
    return _POOL["markets"]


def market(ticker: str) -> tuple[dict, bool]:
    """(market, historical?): the regular endpoint first, then the historical one."""
    try:
        return _get(f"/markets/{ticker}")["market"], False
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    return _get(f"/historical/markets/{ticker}")["market"], True


def _dollars(side: dict | None) -> float:
    side = side or {}
    v = side.get("close_dollars", side.get("close"))  # historical candles drop the _dollars suffix
    return float(v) if v not in (None, "") else float("nan")


def candles(ticker: str, start_ts: int, end_ts: int, series: str = "KXCS2MAP",
            historical: bool = False) -> pd.DataFrame:
    """1-minute yes bid/ask closes -> mid price, as a DataFrame indexed by unix time."""
    rows = []
    step = 4000 * 60  # stay under the per-request candle cap
    path = f"/historical/markets/{ticker}/candlesticks" if historical else f"/series/{series}/markets/{ticker}/candlesticks"
    for a in range(start_ts, end_ts, step):
        d = _get(path, start_ts=a, end_ts=min(end_ts, a + step), period_interval=1)
        for c in d.get("candlesticks", []):
            rows.append({"ts": int(c["end_period_ts"]), "bid": _dollars(c.get("yes_bid")),
                         "ask": _dollars(c.get("yes_ask")), "last": _dollars(c.get("price")),
                         "volume": float(c.get("volume_fp") or c.get("volume") or 0)})
    df = pd.DataFrame(rows).drop_duplicates("ts").sort_values("ts")
    if df.empty:
        return df
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["spread"] = df["ask"] - df["bid"]
    return df.reset_index(drop=True)


def trades(ticker: str, min_ts: int, max_ts: int, cap: int = 200_000) -> pd.DataFrame:
    """Every trade (ms timestamps) in [min_ts, max_ts]: the finest historical price data Kalshi has.
    Trades older than the cutoff come from /historical/trades, newer ones from /markets/trades."""
    tc = cutoff()["trades"]
    spans = []
    if min_ts < tc:
        spans.append(("/historical/trades", min_ts, min(max_ts, tc)))
    if max_ts > tc:
        spans.append(("/markets/trades", max(min_ts, tc), max_ts))
    rows, ids = [], set()
    for path, lo, hi in spans:
        cursor = None
        while True:
            d = _get(path, ticker=ticker, min_ts=lo, max_ts=hi, limit=1000, cursor=cursor)
            for t in d.get("trades", []):
                if t.get("trade_id") in ids:  # a trade on the boundary second can come from both
                    continue
                ids.add(t.get("trade_id"))
                rows.append({"ts": datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp(),
                             "yes_price": float(t["yes_price_dollars"]), "count": float(t["count_fp"]),
                             "taker_side": t.get("taker_side")})
            cursor = d.get("cursor")
            if not cursor or len(rows) >= cap:
                break
    return pd.DataFrame(rows, columns=["ts", "yes_price", "count", "taker_side"]).sort_values("ts").reset_index(drop=True)


def _demo_series(demo_id: str):
    """Our map win probability for team A by demo second (seconds since first freeze end)."""
    meta = load_meta(demo_id)
    s = pd.read_parquet(storage.local_path(f"scores/{demo_id}.parquet"), columns=["tick", "p_map_a"])
    t0 = meta["rounds"][0]["freeze_end"]
    s["sec"] = (s["tick"] - t0) / TICKRATE
    return meta, s


def auto_align(demo_id: str, cd: pd.DataFrame, yes_is_a: bool) -> int:
    """Best wall-clock start (unix ts of round 1 freeze end): the offset where our per-minute
    map probability best matches the market mid (smallest mean squared gap)."""
    _, s = _demo_series(demo_id)
    ours = s.set_index("sec")["p_map_a"]
    if not yes_is_a:
        ours = 1 - ours
    dur = float(s["sec"].max())
    valid = cd.dropna(subset=["mid"])
    # only minutes that actually traded with a tight book: stale overnight quotes say nothing
    valid = valid[(valid["spread"] <= 0.2) & (valid["volume"] > 0)]
    if len(valid) < 5:
        raise ValueError("too few traded minutes to auto-align; set the start time manually")
    best, best_err = None, np.inf
    lo, hi = int(valid["ts"].min() - dur), int(valid["ts"].max())
    secs = ours.index.to_numpy()
    vals = ours.to_numpy()
    for start in range(lo, hi, 15):
        rel = valid["ts"].to_numpy() - start
        m = (rel >= 0) & (rel <= dur)
        if m.sum() < 5:
            continue
        idx = np.clip(np.searchsorted(secs, rel[m]), 0, len(secs) - 1)
        err = float(np.mean((vals[idx] - valid["mid"].to_numpy()[m]) ** 2))
        if err < best_err:
            best, best_err = start, err
    if best is None:
        raise ValueError("market prices do not overlap the demo length")
    return best


def _per_second(tr: pd.DataFrame, flip: bool) -> pd.Series:
    """Last traded price for team A, one value per wall-clock second."""
    if tr.empty:
        return pd.Series(dtype=float)
    sec = tr["ts"].astype("int64")
    px = (1 - tr["yes_price"]) if flip else tr["yes_price"]
    s = pd.Series(px.to_numpy(), index=sec.to_numpy()).groupby(level=0).last()
    return s.reindex(range(int(s.index.min()), int(s.index.max()) + 1)).ffill()


def _round_events(meta, ours_full) -> list[tuple[int, float]]:
    """(second of round end, how much that result moves the map odds) for decisive rounds.

    Model-free on purpose: the move is computed from the SCORE alone (map odds before vs after the
    round with an even round probability), which is exactly the information a market reacts to at
    the round end. Using our model's in-round odds here made alignment depend on the model (a
    sharper model has already priced the result before the round ends, so the signal vanished)
    and made the quality check circular."""
    t0 = meta["rounds"][0]["freeze_end"]
    last = int(ours_full.index.max()) if len(ours_full) else 0
    out = []
    for r in meta["rounds"]:
        e = int((r["end"] - t0) / TICKRATE)
        if e - 2 < 0 or e + 20 > last or r.get("winner") not in (2, 3):
            continue
        a_won = (r["winner"] == 3) == r["a_is_ct"]
        before = mapwin.map_win_prob(r["a_score"], r["b_score"], r["a_is_ct"], 0.5)
        after = mapwin.map_win_prob(r["a_score"], r["b_score"], r["a_is_ct"], 1.0 if a_won else 0.0)
        if abs(after - before) >= 0.02:
            out.append((e, after - before))
    return out


def _ours_full(s) -> pd.Series:
    ours = s.groupby(s["sec"].astype(int))["p_map_a"].last()
    return ours.reindex(range(0, int(ours.index.max()) + 1)).bfill().ffill()


def _signed_move(mkt: pd.Series, events, start: int, a: int, b: int) -> tuple[float, int]:
    """Mean market move between (end+a, end+b), signed by the direction each round went."""
    vals = []
    for e, d_o in events:
        x0, x1 = mkt.get(start + e + a), mkt.get(start + e + b)
        if x0 is not None and x1 is not None and np.isfinite(x0) and np.isfinite(x1):
            vals.append((x1 - x0) * np.sign(d_o))
    return (float(np.mean(vals)), len(vals)) if vals else (np.nan, 0)


def _objective(mkt: pd.Series, events, start: int) -> float:
    """Market move in each round's direction right after its end, minus any move before it."""
    post, n = _signed_move(mkt, events, start, -20, 60)
    pre, _ = _signed_move(mkt, events, start, -80, -20)
    if n < max(5, len(events) // 2) or not np.isfinite(post):
        return -np.inf
    return post - abs(pre if np.isfinite(pre) else 0.0)


def align_trades(demo_id: str, tr: pd.DataFrame, yes_is_a: bool, close_ts: int | None = None) -> int:
    """Wall-clock unix time of round-1 freeze end.

    Every round result moves the true map odds, so at the right alignment the market moves in the
    round's direction right AFTER each round end and is flat before it. Search the window allowed
    by the market's close time (a map market closes when the map ends) for the offset that
    maximises (move after) - (move before), signed by each round's result."""
    meta, s = _demo_series(demo_id)
    ours = _ours_full(s)
    dur = int(ours.index.max())
    mkt = _per_second(tr, flip=not yes_is_a)
    if len(mkt) < 60:
        raise ValueError("too few trades to align")
    events = _round_events(meta, ours)
    if len(events) < 5:
        raise ValueError("too few decisive rounds to align")
    lo, hi = int(mkt.index.min()) - dur, int(mkt.index.max())
    if close_ts:
        # Round 1 started about (close - map length); allow 20 min of broadcast delay +
        # settlement lag one way and 2 min the other.
        lo, hi = max(lo, close_ts - dur - 1200), min(hi, close_ts - dur + 120)
        if hi <= lo:
            raise ValueError("market close time does not fit this map's length")

    def obj(start):
        return _objective(mkt, events, start)

    best = max(range(lo, hi + 1, 10), key=obj)
    best = max(range(best - 12, best + 13), key=obj)
    if not np.isfinite(obj(best)):
        raise ValueError("market trading does not overlap the map; set the start time manually")
    return int(best)


def link(demo_id: str, ticker: str, yes_team: str, start_ts: int | None = None) -> dict:
    """Attach a Kalshi market to a demo. yes_team is 'a' or 'b' (which of our teams YES pays on)."""
    m, historical = market(ticker)
    series = ticker.split("-")[0]
    close = _ts(m["close_time"])
    opened = _ts(m["open_time"])
    cd = candles(ticker, max(opened, close - 8 * 3600), close, series, historical)
    tr_all = trades(ticker, max(opened, close - 8 * 3600), close + 600)
    aligned_by = "manual"
    if start_ts is None:
        try:
            start_ts, aligned_by = align_trades(demo_id, tr_all, yes_team == "a", close), "trades + close time"
        except ValueError:
            start_ts, aligned_by = auto_align(demo_id, cd, yes_team == "a"), "candles"
    info = {"demo_id": demo_id, "ticker": ticker, "series": series, "title": m.get("title"),
            "yes_team": yes_team, "start_ts": int(start_ts), "result": m.get("result"),
            "aligned_by": aligned_by, "close_ts": int(close), "historical": historical,
            "linked_at": time.time()}
    (LINKS / f"{demo_id}.json").write_text(json.dumps(info))
    cd.to_parquet(LINKS / f"{demo_id}_candles.parquet", index=False)
    storage.publish(f"kalshi/{demo_id}.json", f"kalshi/{demo_id}_candles.parquet")
    # trade tape around the match (alignment can be nudged later, so keep a wide window)
    tr = tr_all
    tr.to_parquet(LINKS / f"{demo_id}_trades.parquet", index=False)
    storage.publish(f"kalshi/{demo_id}_trades.parquet")
    info["n_trades"] = len(tr)
    return info


def realign(demo_id: str) -> dict:
    """Re-fit the start time of an existing link from its stored trade tape (no Kalshi calls)."""
    info = link_info(demo_id)
    if info is None:
        raise ValueError("no Kalshi market linked")
    tr = _maybe_trades(demo_id, info)
    close = info.get("close_ts") or (int(tr["ts"].max()) if len(tr) else None)  # trading stops at close
    info["start_ts"] = align_trades(demo_id, tr, info["yes_team"] == "a", close)
    info["aligned_by"] = "trades + close time (realigned)"
    p = LINKS / f"{demo_id}.json"
    p.write_text(json.dumps(info))
    storage.publish(f"kalshi/{demo_id}.json")
    return info


def _maybe_trades(demo_id: str, info: dict) -> pd.DataFrame:
    key = f"kalshi/{demo_id}_trades.parquet"
    if storage.exists(key):
        return pd.read_parquet(storage.local_path(key))
    return pd.DataFrame(columns=["ts", "yes_price", "count", "taker_side"])


def round_trades(demo_id: str, round_no: int) -> dict | None:
    """Kalshi trades during one round, mapped onto demo ticks and expressed for team A."""
    info = link_info(demo_id)
    if info is None:
        return None
    meta = load_meta(demo_id)
    r = next(x for x in meta["rounds"] if x["round"] == round_no)
    t0 = meta["rounds"][0]["freeze_end"]
    tr = _maybe_trades(demo_id, info)
    tr = tr.assign(tick=(t0 + (tr["ts"] - info["start_ts"]) * TICKRATE).round().astype("int64"))
    flip = info["yes_team"] == "b"
    # last trade before the round starts, so the price is known from the first tick
    before = tr[tr["tick"] < r["freeze_end"]].tail(1)
    inside = tr[(tr["tick"] >= r["freeze_end"]) & (tr["tick"] <= r["end"] + 3 * TICKRATE)]
    out = pd.concat([before, inside])
    price = (1 - out["yes_price"]) if flip else out["yes_price"]
    return {"ticker": info["ticker"], "yes_team": info["yes_team"],
            "tick": out["tick"].tolist(), "price_a": [round(float(x), 4) for x in price],
            "count": [round(float(x), 2) for x in out["count"]],
            "ts": [round(float(x), 3) for x in out["ts"]]}


def comparison(demo_id: str) -> dict | None:
    """Market mid vs our map probability (for team A), both on the demo-seconds axis."""
    info = link_info(demo_id)
    if info is None:
        return None
    cd = pd.read_parquet(storage.local_path(f"kalshi/{demo_id}_candles.parquet"))
    meta, s = _demo_series(demo_id)
    t0 = meta["rounds"][0]["freeze_end"]
    cd["sec"] = cd["ts"] - info["start_ts"]
    flip = info["yes_team"] == "b"
    market = [{"sec": float(r.sec), "tick": int(t0 + r.sec * TICKRATE),
               "mid_a": None if np.isnan(r.mid) else round(float(1 - r.mid if flip else r.mid), 4),
               "bid_a": None if np.isnan(r.bid) else round(float(1 - r.ask if flip else r.bid), 4),
               "ask_a": None if np.isnan(r.ask) else round(float(1 - r.bid if flip else r.ask), 4),
               "volume": float(r.volume)}
              for r in cd.itertuples() if -600 <= r.sec <= s["sec"].max() + 600]
    per_min = s.groupby((s["sec"] // 60).astype(int))["p_map_a"].last()
    ours = [{"sec": float(k * 60 + 59), "p_map_a": round(float(v), 4)} for k, v in per_min.items()]
    # how far apart are we, on minutes where the market had a usable quote?
    gaps = []
    for mk in market:
        if mk["mid_a"] is None or mk["sec"] < 0 or mk["ask_a"] - mk["bid_a"] > 0.2:
            continue
        k = int(mk["sec"] // 60)
        if k in per_min.index:
            gaps.append(abs(float(per_min[k]) - mk["mid_a"]))
    return {**info, "teams": meta.get("teams"), "market": market, "ours_per_minute": ours,
            "mean_abs_gap": round(float(np.mean(gaps)), 4) if gaps else None, "n_compared": len(gaps)}


DATES = (r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}"
         r"(?: at \d{1,2}(?::\d{2})? ?[ap]\.?m\.?(?: [a-z]{2,4})?)?")


def find_market(demo_id: str) -> dict:
    """Kalshi map market for this demo: both team names in the market rules + the map number
    (HLTV demo names end in -m<N>-<map>.dem). YES team is matched to our team A or B."""
    import re

    from cs2wp_core import db
    meta = load_meta(demo_id)
    a, b = meta["teams"]["a"]["name"], meta["teams"]["b"]["name"]
    if a in ("Team A", "Team B") or b in ("Team A", "Team B"):
        raise ValueError("demo has no team names; link a market manually")
    row = db.rows("SELECT filename FROM demos WHERE id=?", (demo_id,))
    fname = row[0]["filename"] if row else ""
    m = re.search(r"-m(\d)-", fname)
    map_no = int(m.group(1)) if m else None
    # HLTV archive names start with the event: "<id8>-esl-pro-league-season-24-aurora-vs-vitality-bo3-..."
    ev = re.match(r"^(?:[0-9a-f]{8}-)?(.+?)-[a-z0-9]+-vs-[a-z0-9]+-bo\d", fname.lower())
    # Kalshi writes the event differently ("ESL Pro League 2026" vs HLTV "...season-24"), so only
    # compare distinctive words: drop numbers and generic words like season / stage / group.
    generic = {"season", "stage", "group", "playoffs", "playoff", "regular", "finals", "final", "day",
               "fall", "spring", "summer", "winter", "the", "of", "cs2", "cs"}
    event_tokens = [t for t in (ev.group(1).split("-") if ev else []) if not t.isdigit() and t not in generic]

    def norm(x):
        x = re.sub(r"\b(team|esports|gaming|club)\b", "", x.lower())  # "Team Vitality" == "Vitality"
        return re.sub(r"[^a-z0-9]", "", x)

    # name variants: demo names ("NaVi", "FaZe Clan") + known aliases
    alias = {"navi": ["natusvincere"], "natusvincere": ["navi"], "nip": ["ninjasinpyjamas"],
             "fazeclan": ["faze"], "g2esports": ["g2"], "mibrlos": ["mibr"], "ninjasinpyjamasestar": ["nip", "ninjasinpyjamas"]}

    def variants(name):
        v = {norm(name)}
        v |= set(alias.get(norm(name), []))
        return {x for x in v if len(x) >= 2}
    va, vb = variants(a), variants(b)
    cands = []
    # every CS2 map market in the window (one listing, cached), matched locally: Kalshi's wording of
    # team names ("Natus Vincere", "FaZe") rarely equals the demo's, so a text query misses markets
    pool = _all_markets(days=400)
    for mk in pool:
        rules = norm(mk.get("rules", ""))
        # team names: the rules name both teams ("...ESL Pro League 2026: MOUZ vs. Vitality CS2 match
        # originally scheduled for Oct 11, 2026 at 10:00 AM EDT..."), minus dates and times, which
        # would otherwise match short names ("aug28" contains "g2")
        names = norm(re.sub(DATES, " ", f"{mk.get('title') or ''} {mk.get('yes_team') or ''} {mk.get('rules') or ''}"))
        if not any(x in names for x in va) or not any(x in names for x in vb):
            continue
        # same event (teams meet at many events); the rules name the tournament
        if event_tokens and sum(norm(t) in rules for t in event_tokens) < 0.6 * len(event_tokens):
            continue
        if map_no and f"map{map_no}" not in norm(mk.get("title") or ""):
            continue
        yes = norm(mk.get("yes_team") or "")
        side = "a" if yes and any(yes in x or x in yes for x in va) else "b"
        cands.append({**mk, "yes_team": side, "map_no": map_no})
    if not cands:
        raise ValueError(f"no Kalshi map market found for {a} vs {b}" + (f" map {map_no}" if map_no else "")
                         + (f" at {' '.join(event_tokens)}" if event_tokens else ""))
    # one candidate per event (the same teams meet many times), YES = team A preferred, newest first
    cands.sort(key=lambda c: (c["yes_team"] != "a", -(_ts(c["close_time"]) if c["close_time"] else 0)))
    per_event = {}
    for c in cands:
        per_event.setdefault(c["ticker"].rsplit("-", 1)[0], c)
    return list(per_event.values())


def _a_won(meta) -> bool:
    last = meta["rounds"][-1]
    a_won_last = (last["winner"] == 3) == last["a_is_ct"]
    return last["a_score"] + int(a_won_last) > last["b_score"] + int(not a_won_last)


def unlink(demo_id: str) -> None:
    """Forget a map's Kalshi link (and its stored prices)."""
    s = storage.store()
    for k in (f"kalshi/{demo_id}.json", f"kalshi/{demo_id}_candles.parquet", f"kalshi/{demo_id}_trades.parquet"):
        s.delete(k)


def _event(ticker: str) -> str:
    """Kalshi match (event) of a map market: KXCS2MAP-26AUG210700MOUZFUT-2-MOUZ -> ...MOUZFUT-2 minus the map."""
    return ticker.rsplit("-", 2)[0]


def _agrees(mk: dict, demo_id: str) -> bool:
    """A settled market must agree with who won this map in the demo."""
    if mk.get("result") not in ("yes", "no"):
        return True
    a_won = _a_won(load_meta(demo_id))
    yes_side_won = a_won if mk["yes_team"] == "a" else not a_won
    return (mk["result"] == "yes") == yes_side_won


def auto_link_match(demo_ids: list[str], max_events: int = 8) -> dict[str, dict]:
    """Link every map of one match to the SAME Kalshi match. The same teams often meet several
    times (twice at one event, again at the next), so:
    1) a Kalshi match qualifies only if its settled results agree with EVERY map we have
       (2-0 and 2-1 meetings separate here);
    2) if several still qualify, the one whose prices jump in line with round results across all
       maps wins. Maps Kalshi did not list stay unlinked. Returns {demo_id: link info}."""
    cands: dict[str, dict[str, dict]] = {}
    for d in demo_ids:
        try:
            cands[d] = {_event(c["ticker"]): c for c in find_market(d)}
        except ValueError:
            cands[d] = {}
    have = {d: c for d, c in cands.items() if c}
    if not have:
        raise ValueError("no Kalshi map market found for this match")
    events = set().union(*have.values())
    ok = [ev for ev in events if all(_agrees(c[ev], d) for d, c in have.items() if ev in c)]
    if not ok:
        raise ValueError("no Kalshi match agrees with these map results")
    newest = {ev: max(_ts(c[ev]["close_time"]) for c in have.values() if ev in c and c[ev].get("close_time")) for ev in ok}
    # prefer Kalshi matches that list the most of our maps, then the most recent
    ok.sort(key=lambda ev: (-sum(ev in c for c in have.values()), -newest.get(ev, 0)))
    best = ok[0]
    if len(ok) > 1:
        fit = {}
        for ev in ok[:max_events]:
            total = 0.0
            for d, c in have.items():
                if ev not in c:
                    continue
                try:
                    link(d, c[ev]["ticker"], c[ev]["yes_team"])
                    q = (analysis(d) or {}).get("alignment") or {}
                    total += q["post_move"] if q.get("post_move") is not None else -1.0
                except ValueError:
                    total -= 1.0
            fit[ev] = total
        best = max(fit, key=fit.get)
    return {d: link(d, c[best]["ticker"], c[best]["yes_team"]) for d, c in have.items() if best in c}


def analysis(demo_id: str) -> dict | None:
    """How our map odds and the market compare over the map, second by second."""
    info = link_info(demo_id)
    if info is None:
        return None
    meta, s = _demo_series(demo_id)
    tr = _maybe_trades(demo_id, info)
    mkt = _per_second(tr, flip=info["yes_team"] == "b")
    ours = s.groupby(s["sec"].astype(int))["p_map_a"].last()
    t0 = meta["rounds"][0]["freeze_end"]
    wall = ours.index + info["start_ts"]
    m_at = mkt.reindex(wall).to_numpy()
    df = pd.DataFrame({"sec": ours.index, "ours": ours.to_numpy(), "mkt": m_at}).dropna()
    if df.empty:
        return {"n_seconds": 0}
    last = meta["rounds"][-1]
    a_won_last = (last["winner"] == 3) == last["a_is_ct"]
    fa = last["a_score"] + int(a_won_last)
    fb = last["b_score"] + int(not a_won_last)
    outcome = 1.0 if fa > fb else 0.0
    gap = df["ours"] - df["mkt"]

    # lead/lag: correlate 1 s changes; positive lag = market moves AFTER our model
    d_o, d_m = df["ours"].diff().fillna(0).to_numpy(), df["mkt"].diff().fillna(0).to_numpy()
    lags = range(-60, 61)

    def xc(k):
        a_, b_ = (d_o[:-k], d_m[k:]) if k > 0 else (d_o[-k:], d_m[:len(d_m) + k]) if k < 0 else (d_o, d_m)
        return float(np.corrcoef(a_, b_)[0, 1]) if len(a_) > 30 and a_.std() > 0 and b_.std() > 0 else 0.0
    xcs = {k: xc(k) for k in lags}
    best_lag = max(xcs, key=lambda k: xcs[k])

    # biggest disagreements, at most one per round
    rnds = sorted(meta["rounds"], key=lambda r: r["freeze_end"])
    starts = np.array([r["freeze_end"] for r in rnds])

    def round_of(sec):
        tick = t0 + sec * TICKRATE
        i = int(np.searchsorted(starts, tick, side="right") - 1)
        return rnds[max(i, 0)], tick

    picks, seen = [], set()
    for idx in gap.abs().sort_values(ascending=False).index:
        r, tick = round_of(int(df.at[idx, "sec"]))
        if r["round"] in seen:
            continue
        seen.add(r["round"])
        picks.append({"round": r["round"], "tick": int(tick), "round_secs": round((tick - r["freeze_end"]) / TICKRATE, 1),
                      "ours": round(float(df.at[idx, "ours"]), 3), "market": round(float(df.at[idx, "mkt"]), 3),
                      "gap": round(float(gap[idx]), 3), "score": f"{r['a_score']}-{r['b_score']}"})
        if len(picks) == 6:
            break

    return {
        "ticker": info["ticker"], "teams": meta.get("teams"), "final": f"{fa}-{fb}",
        "team_a_won": bool(outcome), "n_seconds": int(len(df)), "n_trades": int(len(tr)),
        "aligned_by": info.get("aligned_by"), "start_ts": info["start_ts"],
        "mean_abs_gap": round(float(gap.abs().mean()), 4),
        "mean_gap": round(float(gap.mean()), 4),  # + = we rate team A higher than the market
        "level_corr": round(float(np.corrcoef(df["ours"], df["mkt"])[0, 1]), 3) if df["mkt"].std() > 0 else None,
        "brier_ours": round(float(np.mean((df["ours"] - outcome) ** 2)), 4),
        "brier_market": round(float(np.mean((df["mkt"] - outcome) ** 2)), 4),
        "lag_secs": int(best_lag), "lag_corr": round(xcs[best_lag], 3),
        "alignment": alignment_quality(demo_id),
        "disagreements": picks,
    }


def alignment_quality(demo_id: str) -> dict:
    """Per-map check that demo time and market time line up: flat market BEFORE round ends, a
    move in the round's direction just AFTER, and a clear peak at offset 0 when the same signal
    is re-fit over +-5 minutes."""
    info = link_info(demo_id)
    if info is None:
        return {"confidence": "unlinked"}
    meta, s = _demo_series(demo_id)
    mkt = _per_second(_maybe_trades(demo_id, info), flip=info["yes_team"] == "b")
    if mkt.empty:
        return {"confidence": "none", "reason": "no trades"}
    events = _round_events(meta, _ours_full(s))
    if len(events) < 5:
        return {"confidence": "none", "reason": "too few decisive rounds", "n_events": len(events)}
    start = int(info["start_ts"])
    pre, _ = _signed_move(mkt, events, start, -80, -20)
    post, n_post = _signed_move(mkt, events, start, -20, 60)
    curve = {k: _objective(mkt, events, start + k) for k in range(-300, 301, 10)}
    valid = {k: v for k, v in curve.items() if np.isfinite(v)}
    peak = max(valid, key=valid.get) if valid else None
    vals = np.array(list(valid.values()))
    sharp = float((valid.get(0, np.nan) - np.median(vals)) / (vals.std() + 1e-9)) if len(vals) > 5 else np.nan
    # Rounds come every ~2 min, so the signal is quasi-periodic: shifting by about one round can
    # partly line up again. So require the chosen offset to score near the best within +-5 min
    # (same objective the alignment maximises), plus a real post-round move and a flat market before.
    best_val = max(valid.values()) if valid else np.nan
    here = _objective(mkt, events, start)
    if not np.isfinite(post) or n_post < 5 or not np.isfinite(here):
        conf = "none"
    elif post > 0.01 and post > 2 * abs(pre if np.isfinite(pre) else 0) and here >= 0.8 * best_val:
        conf = "good"
    elif post > 0.005 and here >= 0.6 * best_val:
        conf = "weak"
    else:
        conf = "bad"
    return {"confidence": conf, "n_events": n_post, "pre_move": round(pre, 4) if np.isfinite(pre) else None,
            "post_move": round(post, 4), "best_offset_s": peak, "best_move": round(best_val, 4) if np.isfinite(best_val) else None,
            "sharpness": round(sharp, 2) if np.isfinite(sharp) else None}
