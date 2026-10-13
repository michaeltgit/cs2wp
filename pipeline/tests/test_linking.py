"""Kalshi market selection + alignment (pure logic, no network)."""

import numpy as np
import pandas as pd

from cs2wp_core import mapwin
from cs2wp_pipeline import kalshi


# ---------------- Kalshi market selection ----------------
def _mk(ticker, yes, title_teams, event, close, result=None):
    a, b = title_teams
    # newer markets title only the YES team ("Team Falcons wins map 2"); the rules name both
    return {"ticker": ticker, "title": f"{yes} wins map {ticker.split('-')[2]}",
            "yes_team": yes, "close_time": close, "result": result,
            "rules": f"If {yes} wins map {ticker.split('-')[2]} in the {event}: {a} vs. {b} CS2 match originally scheduled for {close[:10]}"}


def _fake_demos(monkeypatch, files: dict, winners: dict | None = None, teams=("Team Vitality", "MOUZ")):
    from cs2wp_core import db
    monkeypatch.setattr(kalshi, "load_meta", lambda d: {
        "teams": {"a": {"name": teams[0]}, "b": {"name": teams[1]}},
        # 12-12, the last round decides: A wins when winners[d] is True
        "rounds": [{"winner": 3, "a_is_ct": bool((winners or {}).get(d, True)), "a_score": 12, "b_score": 12}]})
    monkeypatch.setattr(db, "rows", lambda sql, args=(): [{"filename": f} for d, f in files.items() if not args or d == args[0]])


def test_find_market_filters_event_map_and_side(monkeypatch):
    monkeypatch.setattr(kalshi, "_all_markets", lambda days: [
        _mk("KXCS2MAP-26OCT11MOUZVIT-3-VIT", "Vitality", ("MOUZ", "Vitality"), "ESL Pro League 2026", "2026-10-11T18:14:43Z"),
        _mk("KXCS2MAP-26OCT11MOUZVIT-3-MOUZ", "MOUZ", ("MOUZ", "Vitality"), "ESL Pro League 2026", "2026-10-11T18:14:43Z"),
        _mk("KXCS2MAP-26SEP05VITMOUZ-3-VIT", "Vitality", ("Vitality", "MOUZ"), "BLAST Open Porto 2026", "2026-09-05T18:00:00Z"),
        _mk("KXCS2MAP-26OCT11MOUZVIT-2-VIT", "Vitality", ("MOUZ", "Vitality"), "ESL Pro League 2026", "2026-10-11T17:00:00Z"),
    ])
    _fake_demos(monkeypatch, {"d1": "31c5a883-esl-pro-league-season-24-vitality-vs-mouz-bo5-k-vitality-vs-mouz-m3-dust2.dem"})
    found = kalshi.find_market("d1")
    assert [f["ticker"] for f in found] == ["KXCS2MAP-26OCT11MOUZVIT-3-VIT"]  # event + map 3 + YES = team A
    assert found[0]["yes_team"] == "a"


def test_team_names_come_from_the_title_not_dates(monkeypatch):
    # "Aug 28, 2026" in the rules contains "g2" once punctuation is stripped; that must not match G2
    monkeypatch.setattr(kalshi, "_all_markets", lambda days: [
        _mk("KXCS2MAP-26AUG280500DENAUR-1-AUR", "Aurora", ("Denmark", "Aurora"), "BLAST Open Porto 2026", "2026-08-28T12:00:00Z"),
        _mk("KXCS2MAP-26AUG310730AURG2-1-AUR", "Aurora", ("Aurora", "G2"), "BLAST Open Porto 2026", "2026-08-31T12:00:00Z"),
    ])
    _fake_demos(monkeypatch, {"d1": "blast-open-porto-2026-g2-vs-aurora-bo3-x-g2-vs-aurora-m1-mirage.dem"}, teams=("G2", "Aurora"))
    assert [f["ticker"] for f in kalshi.find_market("d1")] == ["KXCS2MAP-26AUG310730AURG2-1-AUR"]


def test_whole_match_links_to_the_meeting_whose_results_agree(monkeypatch):
    # FUT and MOUZ met twice at one event; our match: A (FUT) lost map 1, won map 2
    ev = "Esports World Cup 2026"
    monkeypatch.setattr(kalshi, "_all_markets", lambda days: [
        _mk("KXCS2MAP-26AUG210700MOUZFUT-1-FUT", "FUT", ("MOUZ", "FUT"), ev, "2026-08-21T12:00:00Z", "yes"),
        _mk("KXCS2MAP-26AUG210700MOUZFUT-2-FUT", "FUT", ("MOUZ", "FUT"), ev, "2026-08-21T13:00:00Z", "yes"),
        _mk("KXCS2MAP-26AUG141000MOUZFUT-1-FUT", "FUT", ("MOUZ", "FUT"), ev, "2026-08-14T12:00:00Z", "no"),
        _mk("KXCS2MAP-26AUG141000MOUZFUT-2-FUT", "FUT", ("MOUZ", "FUT"), ev, "2026-08-14T13:00:00Z", "yes"),
    ])
    files = {"m1": "esports-world-cup-2026-fut-vs-mouz-bo3-k-fut-vs-mouz-m1-nuke.dem",
             "m2": "esports-world-cup-2026-fut-vs-mouz-bo3-k-fut-vs-mouz-m2-mirage.dem"}
    _fake_demos(monkeypatch, files, winners={"m1": False, "m2": True}, teams=("FUT", "MOUZ"))
    monkeypatch.setattr(kalshi, "link", lambda d, ticker, yes, start=None: {"demo_id": d, "ticker": ticker})
    out = kalshi.auto_link_match(["m1", "m2"])
    assert {d: i["ticker"] for d, i in out.items()} == {
        "m1": "KXCS2MAP-26AUG141000MOUZFUT-1-FUT", "m2": "KXCS2MAP-26AUG141000MOUZFUT-2-FUT"}


# ---------------- alignment recovers a known offset ----------------
def test_alignment_recovers_true_start(monkeypatch):
    rng = np.random.default_rng(0)
    tick = 64
    rounds, t, a, b = [], 0, 0, 0
    for i in range(22):  # alternating-ish results, ~100 s rounds with 20 s gaps
        freeze, end = t, t + int((80 + rng.integers(0, 40)) * tick)
        a_won = rng.random() < 0.5
        rounds.append({"round": i + 1, "freeze_end": freeze, "end": end, "a_score": a, "b_score": b,
                       "a_is_ct": True, "winner": 3 if a_won else 2})
        a, b = (a + 1, b) if a_won else (a, b + 1)
        t = end + 20 * tick
    secs, vals = [], []
    for r in rounds:  # our map odds per second: a step at every round end
        sc = mapwin.map_win_prob(r["a_score"], r["b_score"], True, 0.5)
        for sec in range(r["freeze_end"] // tick, r["end"] // tick + 1):
            secs.append(sec)
            vals.append(sc)
    s = pd.DataFrame({"sec": secs, "p_map_a": vals})
    monkeypatch.setattr(kalshi, "_demo_series", lambda d: ({"rounds": rounds}, s))
    true_start, lag = 1_790_000_000, 25  # market reacts 25 s after each round end
    ours = kalshi._ours_full(s)
    rows = []
    for k in range(0, int(ours.index.max()) + 600, 7):
        p = float(ours.get(max(0, k - lag), ours.iloc[-1])) + rng.normal(0, 0.01)
        rows.append({"ts": true_start + k, "yes_price": float(np.clip(p, 0.01, 0.99)), "count": 10.0,
                     "taker_side": "yes"})
    close = true_start + int(ours.index.max()) + 300
    got = kalshi.align_trades("x", pd.DataFrame(rows), True, close)
    assert abs(got - true_start) <= 30  # within the market's reaction lag
