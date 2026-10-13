import asyncio
import json

import pytest
from pydantic import ValidationError

from cs2wp_core import config, storage
from cs2wp_core.bus import InProcessBus
from cs2wp_core.contracts import Command, CommandType, RoundPrediction, Topic


def test_local_store_keys_are_paths():
    s = storage.store()
    p = s.local_path("scores/x.json", fetch=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    (p.parent / "x.json.etag").write_text("cache sidecar, never listed")
    assert storage.key_of(p) == "scores/x.json"
    assert s.exists("scores/x.json") and s.list("scores/") == ["scores/x.json"]
    s.delete("scores/x.json")
    assert not s.exists("scores/x.json")


def test_bucket_routing():
    b = storage.S3Store.bucket_for
    assert b("raw/a.dem") == b("uploads/a.rar") == config.S3_BUCKETS["demos"]
    assert b("models/v001/model.txt") == config.S3_BUCKETS["models"]
    assert b("parsed/a/meta.json") == b("kalshi/a.json") == config.S3_BUCKETS["gs"]


def test_contracts_round_trip():
    c = Command(run_id="r1", type=CommandType.SEEK, args={"tick": 100})
    back = Command.model_validate(json.loads(json.dumps(c.model_dump(mode="json"))))
    assert back.type == CommandType.SEEK and back.args == {"tick": 100} and back.schema_version
    with pytest.raises(ValidationError):
        Command(run_id="r1", type="explode")
    RoundPrediction(run_id="r", tick=1, round=1, p_ct=None, model_version="v1")


def test_inprocess_bus_filters_by_key():
    async def go():
        bus = InProcessBus()
        got_a, got_all = [], []

        async def sub(key, out, n):
            async for m in bus.subscribe(Topic.ROUND_PREDICTIONS.value, key=key):
                out.append(m["i"])
                if len(out) == n:
                    return

        ta = asyncio.create_task(sub("a", got_a, 2))
        tall = asyncio.create_task(sub(None, got_all, 3))
        await asyncio.sleep(0)
        for i, k in enumerate(["a", "b", "a"]):
            await bus.publish(Topic.ROUND_PREDICTIONS.value, {"i": i}, key=k)
        await asyncio.wait_for(asyncio.gather(ta, tall), 2)
        return got_a, got_all

    a, everything = asyncio.run(go())
    assert a == [0, 2] and everything == [0, 1, 2]
