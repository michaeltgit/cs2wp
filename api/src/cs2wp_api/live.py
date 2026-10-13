"""WebSocket gateway for live replay runs.

Browser protocol (unchanged from the prototype UI):
    server -> {"type": "hello", session, first_tick, last_tick, model}
    client -> {"cmd": "play"|"pause"|"seek"|"speed", tick?, value?}
    server -> {"type": "frame", tick, p_ct, series, players, model} | {"type": "error", message}

In-process bus (lite): the run (streamer + inference) is started inside this process.
Kafka bus (stack): the gateway publishes START_RUN / play / seek ... on ``system-commands`` and the
``cs2wp-pipeline runtime`` service runs the streamer + inference; frames come back on
``round-predictions`` keyed by run_id. The gateway is stateless, so the API scales horizontally.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import numpy as np
import pandas as pd
from fastapi import WebSocket, WebSocketDisconnect

from cs2wp_core import config, storage
from cs2wp_core.bus import get_bus
from cs2wp_core.contracts import Command, CommandType, RunStatus, Topic
from cs2wp_core.modeling import predictor_for

KAFKA_SUBSCRIBE_GRACE = 1.5  # seconds for a 'latest' consumer to get its partitions
RUNTIME_START_TIMEOUT = 15.0


def _tick_range(demo_id: str, round_no: int) -> tuple[int, int]:
    t = pd.read_parquet(storage.local_path(f"parsed/{demo_id}/ticks.parquet"), columns=["tick", "round"],
                        filters=[("round", "==", round_no)])
    if t.empty:
        raise ValueError(f"round {round_no} not found in {demo_id}")
    ticks = np.sort(t["tick"].unique())
    return int(ticks[0]), int(ticks[-1])


def _command(run_id: str, msg: dict) -> Command:
    c = msg.get("cmd") or msg.get("type")
    args = {k: v for k, v in msg.items() if k not in ("cmd", "type")}
    return Command(run_id=run_id, type=CommandType(c), args=args)


def _frame(p: dict) -> dict:
    return {"type": "frame", "tick": p["tick"], "p_ct": p["p_ct"], "series": p["series"],
            "players": p["players"], "model": p["model_version"]}


async def serve(ws: WebSocket, demo_id: str, round_no: int):
    await ws.accept()
    run_id = uuid.uuid4().hex[:12]
    bus = get_bus()
    kafka = config.BUS == "kafka"
    try:
        first, last = await asyncio.to_thread(_tick_range, demo_id, round_no)
        fp = json.loads(storage.local_path(f"parsed/{demo_id}/meta.json").read_text()).get("fingerprint")
        model = (await asyncio.to_thread(predictor_for, demo_id, None, fp)).version
        run = None
        if not kafka:
            from cs2wp_pipeline.runtime import Run
            run = await asyncio.to_thread(Run, run_id, demo_id, round_no)
    except Exception as e:  # no trained model, unknown round, demo not parsed ...
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
        return

    async def pump_predictions():
        async for p in bus.subscribe(Topic.ROUND_PREDICTIONS.value, key=run_id):
            await ws.send_json(_frame(p))

    started = asyncio.get_running_loop().create_future()

    async def pump_events():
        async for e in bus.subscribe(Topic.SYSTEM_EVENTS.value, key=run_id):
            st = e.get("status")
            if st == RunStatus.RUNNING.value and not started.done():
                started.set_result(None)
            elif st == RunStatus.FAILED.value:
                if not started.done():
                    started.set_exception(RuntimeError(e.get("message") or "run failed"))
                else:
                    await ws.send_json({"type": "error", "message": e.get("message") or "run failed"})

    pumps = [asyncio.create_task(pump_predictions()), asyncio.create_task(pump_events())]
    try:
        if kafka:
            await asyncio.sleep(KAFKA_SUBSCRIBE_GRACE)  # our consumers must be live before the run starts
            await bus.publish(Topic.SYSTEM_COMMANDS.value, Command(
                run_id=run_id, type=CommandType.START_RUN, args={"demo_id": demo_id, "round": round_no},
            ).model_dump(mode="json"), key=run_id)
            await asyncio.wait_for(started, RUNTIME_START_TIMEOUT)
        else:
            await asyncio.sleep(0)  # let the in-process subscriptions register
            run.start()
    except Exception as e:
        msg = "live runtime not responding (is `cs2wp-pipeline runtime` running?)" \
            if isinstance(e, TimeoutError) else str(e)
        for t in pumps:
            t.cancel()
        await ws.send_json({"type": "error", "message": msg})
        await ws.close()
        return
    await ws.send_json({"type": "hello", "session": run_id, "first_tick": first, "last_tick": last, "model": model})
    try:
        while True:
            try:
                cmd = _command(run_id, json.loads(await ws.receive_text()))
            except (ValueError, KeyError):
                continue
            await bus.publish(Topic.SYSTEM_COMMANDS.value, cmd.model_dump(mode="json"), key=run_id)
    except WebSocketDisconnect:
        pass
    finally:
        for t in pumps:
            t.cancel()
        await bus.publish(Topic.SYSTEM_COMMANDS.value, Command(run_id=run_id, type=CommandType.STOP_RUN)
                          .model_dump(mode="json"), key=run_id)
        if run is not None:
            run.stop()
