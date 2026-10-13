"""Kalshi regular vs /historical endpoint routing, with the HTTP layer faked (no network)."""

import io
import time
import urllib.error
from datetime import UTC

import pytest

from cs2wp_pipeline import kalshi

CUT = 1_786_492_800  # 2026-08-12


@pytest.fixture(autouse=True)
def fixed_cutoff(monkeypatch):
    monkeypatch.setattr(kalshi, "_CUTOFF", {"settled": CUT, "trades": CUT, "at": time.time()})


def _trade(tid, ts, price="0.5000"):
    from datetime import datetime
    iso = datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")
    return {"trade_id": tid, "created_time": iso, "yes_price_dollars": price, "count_fp": "1.00", "taker_side": "yes"}


def test_trades_split_at_cutoff_and_dedupe(monkeypatch):
    calls = []

    def fake_get(path, **q):
        calls.append((path, q["min_ts"], q["max_ts"]))
        if path == "/historical/trades":
            return {"trades": [_trade("a", CUT - 10), _trade("b", CUT)]}
        return {"trades": [_trade("b", CUT), _trade("c", CUT + 10)]}

    monkeypatch.setattr(kalshi, "_get", fake_get)
    tr = kalshi.trades("T", CUT - 100, CUT + 100)
    assert calls == [("/historical/trades", CUT - 100, CUT), ("/markets/trades", CUT, CUT + 100)]
    assert len(tr) == 3 and tr["ts"].is_monotonic_increasing


def test_trades_entirely_on_one_side(monkeypatch):
    paths = []
    monkeypatch.setattr(kalshi, "_get", lambda path, **q: paths.append(path) or {"trades": []})
    kalshi.trades("T", CUT - 500, CUT - 100)
    kalshi.trades("T", CUT + 100, CUT + 500)
    assert paths == ["/historical/trades", "/markets/trades"]


def test_market_falls_back_to_historical(monkeypatch):
    def fake_get(path, **q):
        if path == "/markets/T":
            raise urllib.error.HTTPError(path, 404, "not found", {}, io.BytesIO())
        return {"market": {"ticker": "T"}}

    monkeypatch.setattr(kalshi, "_get", fake_get)
    assert kalshi.market("T") == ({"ticker": "T"}, True)


def test_historical_candles_without_dollars_suffix(monkeypatch):
    seen = []

    def fake_get(path, **q):
        seen.append(path)
        return {"candlesticks": [{"end_period_ts": 100, "yes_bid": {"close": "0.4000"}, "yes_ask": {"close": "0.4600"},
                                  "price": {"close": "0.4400"}, "volume": "12.00"}]}

    monkeypatch.setattr(kalshi, "_get", fake_get)
    cd = kalshi.candles("T", 0, 60, historical=True)
    assert seen == ["/historical/markets/T/candlesticks"]
    assert cd.loc[0, "mid"] == pytest.approx(0.43) and cd.loc[0, "volume"] == 12.0


def test_search_includes_historical_inside_the_window(monkeypatch):
    def iso(ts):
        from datetime import datetime
        return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")

    now = int(time.time())
    # cutoff 100 days ago (relative, so the test does not age)
    monkeypatch.setattr(kalshi, "_CUTOFF", {"settled": now - 100 * 86400, "trades": now - 100 * 86400, "at": now})
    old = {"ticker": "OLD", "title": "Vitality vs Spirit map 1", "rules_primary": "Vitality Spirit", "close_time": iso(now - 200 * 86400)}
    ancient = {**old, "ticker": "ANCIENT", "close_time": iso(now - 900 * 86400)}
    monkeypatch.setattr(kalshi, "_get", lambda path, **q: {"markets": []})
    monkeypatch.setattr(kalshi, "_historical_markets", lambda series: [old, ancient])
    tickers = [m["ticker"] for m in kalshi.search_markets("vitality", days=400)]
    assert tickers == ["OLD"]
    assert kalshi.search_markets("vitality", days=30) == []  # window ends after the cutoff: no historical lookup
