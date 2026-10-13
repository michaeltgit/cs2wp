"""Parse -> features -> live replay on a real CS2 demo. Skipped unless CS2WP_TEST_DEMO points at a
.dem file (e.g. demoparser2's public test demo; scripts/seed.py --with-raw downloads one)."""

import asyncio
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from cs2wp_core import db, features, storage

DEMO = os.environ.get("CS2WP_TEST_DEMO")
pytestmark = pytest.mark.skipif(not DEMO or not Path(DEMO).exists(), reason="set CS2WP_TEST_DEMO=/path/to.dem")
DEMO_ID = "test-demo-e2e"


@pytest.fixture(scope="module")
def parsed():
    from cs2wp_pipeline import parse
    db.init()
    dest = storage.local_path(f"raw/{DEMO_ID}.dem", fetch=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(DEMO, dest)
    db.add_demo(DEMO_ID, Path(DEMO).name, "e2e-sha")
    parse.parse_demo(DEMO_ID)
    return parse.load(DEMO_ID)


def test_rounds_and_labels(parsed):
    meta, ticks, _ = parsed
    assert len(meta["rounds"]) >= 5
    assert all(r["winner"] in (2, 3) for r in meta["rounds"])
    assert set(ticks["team_num"].unique()) <= {2, 3}


def test_full_tick_rate(parsed):
    meta, ticks, _ = parsed
    r = meta["rounds"][0]
    assert len(ticks[ticks["round"] == r["round"]]["tick"].unique()) >= (r["end"] - r["freeze_end"])


def test_features_no_lookahead(parsed):
    """Features at a tick must not change when later ticks/events are removed (live == batch)."""
    meta, ticks, events = parsed
    r = meta["rounds"][1]
    full = features.build(meta, ticks, events)
    cut = r["freeze_end"] + 30 * 64
    live = features.build(meta, ticks[ticks["tick"] <= cut], events[events["tick"] <= cut])
    a = full[(full["round"] == r["round"]) & (full["tick"] == cut)].drop(columns=["ct_win", "valid"])
    b = live[(live["round"] == r["round"]) & (live["tick"] == cut)].drop(columns=["ct_win", "valid"])
    assert len(a) == 1
    assert a.reset_index(drop=True).equals(b.reset_index(drop=True))


def test_live_batches_match_batch(parsed):
    meta, ticks, events = parsed
    for r in meta["rounds"][:3]:
        m = {**meta, "rounds": [r]}
        rt, re_ = ticks[ticks["round"] == r["round"]], events[events["round"] == r["round"]]
        full = features.build(m, rt, re_).set_index("tick")
        tl = sorted(full.index)
        for i in range(0, len(tl), 17):
            due = tl[i:i + 17]
            b = features.build(m, rt[rt["tick"].isin(due)], re_[re_["tick"] <= max(due)]).set_index("tick")
            a = full.loc[b.index]
            for c in features.FEATURES:
                if c == "map":
                    continue
                x, y = a[c].astype(float).to_numpy(), b[c].astype(float).to_numpy()
                assert (np.isnan(x) == np.isnan(y)).all(), c
                assert np.nanmax(np.abs(x - y), initial=0) < 1e-6, c


def test_replay_run_streams_predictions(parsed, monkeypatch):
    """ReplayStreamer -> raw-gs -> LiveInference -> round-predictions on the in-process bus."""
    from cs2wp_core.bus import get_bus
    from cs2wp_core.contracts import Command, CommandType, Topic
    from cs2wp_pipeline import runtime

    class Stub:
        version = "stub"

        def predict(self, f):
            return np.full(len(f), 0.5)

    monkeypatch.setattr(runtime, "predictor_for", lambda d, **kw: Stub())
    meta = parsed[0]

    async def go():
        run = runtime.Run("r1", DEMO_ID, meta["rounds"][0]["round"])
        got = []

        async def collect():
            async for p in get_bus().subscribe(Topic.ROUND_PREDICTIONS.value, key="r1"):
                got.append(p)
                if len(got) >= 5:
                    return

        t = asyncio.create_task(collect())
        await asyncio.sleep(0)
        run.start()
        await asyncio.sleep(0)
        await get_bus().publish(Topic.SYSTEM_COMMANDS.value, Command(
            run_id="r1", type=CommandType.SPEED, args={"value": 4}).model_dump(mode="json"), key="r1")
        await get_bus().publish(Topic.SYSTEM_COMMANDS.value, Command(
            run_id="r1", type=CommandType.PLAY).model_dump(mode="json"), key="r1")
        await asyncio.wait_for(t, 10)
        run.stop()
        return got

    got = asyncio.run(go())
    ticks = [p["tick"] for p in got]
    assert ticks == sorted(ticks) and all(p["p_ct"] == 0.5 and len(p["players"]) == 10 for p in got)


def test_validation_gate_live_equals_batch(parsed):
    """Replay frames through the wire format + live inference give the same features and P(CT) as
    batch scoring at every tick (the check to repeat on GRID data before trusting it)."""
    from cs2wp_core.modeling import MODEL_FEATURES
    from cs2wp_pipeline.validate import live_vs_batch

    class Linear:  # sensitive to every model feature, so any feature mismatch moves P
        version = "linear-check"
        features = MODEL_FEATURES

        def predict(self, f):
            x = sum(f[c].astype(float).fillna(0).to_numpy() * (i + 1) * 1e-3 for i, c in enumerate(MODEL_FEATURES) if c != "map")
            return 1 / (1 + np.exp(-np.clip(x, -50, 50)))

    meta = parsed[0]
    r = live_vs_batch(DEMO_ID, [x["round"] for x in meta["rounds"][:3]], predictor=Linear(), chunks=(1, 17, 64))
    assert r["ok"], r["mismatches"]
    assert r["ticks_compared"] > 1000 and r["max_p_diff"] == 0.0
