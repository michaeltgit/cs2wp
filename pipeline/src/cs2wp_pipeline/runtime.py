"""Live runtime: one shared inference path for replay (and, later, GRID).

    ReplayStreamer --raw-gs--> LiveInference --round-predictions--> (API WebSocket gateway)
          ^                                                                  |
          +------------------------- system-commands <-----------------------+

* Every message follows ``cs2wp_core.contracts`` and is keyed by ``run_id``.
* The streamer emits canonical RawGS frames (player ticks + events so far + round context), so a
  GRID adapter only has to emit the same frames; consumers never branch on the source.
* Features at a tick only use data at or before it, so live == batch (tested).
* Works on the in-process bus (single process, dev) or Kafka/Redpanda (``CS2WP_BUS=kafka``):
  run ``cs2wp-pipeline runtime`` next to the API and runs are started via system-commands.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pandas as pd

from cs2wp_core import features, storage
from cs2wp_core.bus import get_bus
from cs2wp_core.config import TICKRATE
from cs2wp_core.contracts import Command, CommandType, RawGSFrame, RoundPrediction, RunStatus, SystemEvent, Topic
from cs2wp_core.modeling import predictor_for

from .parse import load_meta

FRAME_SECS = 1 / 30
TICK_COLUMNS = ["tick", "steamid", "name", "team_num", "X", "Y", "Z", "yaw", "is_alive", "health",
                "armor_value", "has_helmet", "has_defuser", "current_equip_value", "balance", "inventory",
                "active_weapon_name", "is_defusing", "flash_duration", "is_bomb_planted", "is_bomb_dropped",
                "in_bomb_zone", "last_place_name", "game_time", "round_start_time", "round"]


def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(float(v)) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [str(x) for x in v.tolist()]
    if v is pd.NA:
        return None
    return v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict("records")]


class ReplayStreamer:
    """Plays one stored round in real time as RawGS frames. Commands: play, pause, seek(tick),
    speed(x; negative = rewind). Each frame carries every tick that became due since the last
    frame, so 64 Hz data is never skipped at 1x; a seek while paused emits one frame."""

    def __init__(self, run_id: str, demo_id: str, round_no: int):
        self.run_id, self.demo_id, self.round_no = run_id, demo_id, round_no
        meta = load_meta(demo_id)
        self.round = next((r for r in meta["rounds"] if r["round"] == round_no), None)
        if self.round is None:
            raise ValueError(f"round {round_no} not found in {demo_id}")
        self.round_meta = {"demo_id": demo_id, "map": meta["map"],
                           "teams": meta.get("teams"), "rounds": [self.round]}
        ticks = pd.read_parquet(storage.local_path(f"parsed/{demo_id}/ticks.parquet"),
                                filters=[("round", "==", round_no)])
        self.ticks = ticks[[c for c in TICK_COLUMNS if c in ticks.columns]]
        ev = pd.read_parquet(storage.local_path(f"parsed/{demo_id}/events.parquet"))
        self.events = ev[ev["round"] == round_no]
        self.tick_list = np.sort(self.ticks["tick"].unique())
        self.pos, self.playing, self.speed, self.dirty, self.seq = 0, False, 1.0, False, 0
        self.stopped = False

    def command(self, cmd: dict):
        c = cmd.get("type") or cmd.get("cmd")
        args = cmd.get("args") or cmd
        if c == "play":
            self.playing = True
        elif c == "pause":
            self.playing = False
        elif c == "seek":
            self.pos = int(np.clip(np.searchsorted(self.tick_list, int(args["tick"])), 0, len(self.tick_list) - 1))
            self.dirty = True
        elif c == "speed":
            self.speed = float(np.clip(float(args["value"]), -8, 8))
        elif c == "stop_run":
            self.stopped = True

    def frame(self, due) -> dict:
        """The RawGS message for these ticks, exactly as it goes on the wire (JSON-ready)."""
        batch = self.ticks[self.ticks["tick"].isin(due)]
        evs = self.events[self.events["tick"] <= int(max(due))]
        self.seq += 1
        return RawGSFrame(run_id=self.run_id, sequence=self.seq, demo_id=self.demo_id, map=self.round_meta["map"],
                          round=self.round_no, ticks=_records(batch), events=_records(evs),
                          round_meta=self.round_meta).model_dump(mode="json")

    async def _publish(self, due):
        await get_bus().publish(Topic.RAW_GS.value, self.frame(due), key=self.run_id)

    async def run(self):
        carry = 0.0
        while not self.stopped:
            await asyncio.sleep(FRAME_SECS)
            if not self.playing:
                if self.dirty:
                    self.dirty = False
                    await self._publish(self.tick_list[self.pos:self.pos + 1])
                continue
            carry += FRAME_SECS * TICKRATE * self.speed
            step = int(carry)
            carry -= step
            if step == 0:
                continue
            lo, hi = sorted((self.pos, self.pos + step))
            lo, hi = max(lo, 0), min(hi, len(self.tick_list) - 1)
            self.pos = hi if step > 0 else lo
            due = self.tick_list[lo:hi + 1] if step > 0 else self.tick_list[lo:lo + 1]
            if (step > 0 and self.pos >= len(self.tick_list) - 1) or (step < 0 and self.pos <= 0):
                self.playing = False
            await self._publish(due)


def infer_frame(frame: dict, pred) -> tuple[pd.DataFrame, np.ndarray]:
    """Shared feature lib + model on one RawGS frame (identical to batch scoring)."""
    ticks = pd.DataFrame(frame["ticks"])
    events = pd.DataFrame(frame["events"]) if frame["events"] else pd.DataFrame(columns=["tick", "type", "round"])
    if "round" not in ticks:
        ticks["round"] = frame["round"]
    f = features.build(frame["round_meta"], ticks, events, every=1)
    return f, (pred.predict(f) if len(f) else np.array([]))


class LiveInference:
    """Consumes raw-gs for one run, publishes round-predictions (with a radar projection)."""

    def __init__(self, run_id: str, demo_id: str):
        self.run_id = run_id
        self.pred = predictor_for(demo_id, fingerprint=load_meta(demo_id).get("fingerprint"))

    async def run(self):
        bus = get_bus()
        async for frame in bus.subscribe(Topic.RAW_GS.value, key=self.run_id):
            try:
                f, p = await asyncio.to_thread(infer_frame, frame, self.pred)
            except Exception as e:  # report instead of dying silently
                await bus.publish(Topic.SYSTEM_EVENTS.value, SystemEvent(
                    run_id=self.run_id, status=RunStatus.FAILED, message=f"inference failed: {e}").model_dump(mode="json"),
                    key=self.run_id)
                continue
            ticks = frame["ticks"]
            if not ticks:
                continue
            last_tick = max(t["tick"] for t in ticks)
            players = [{"steamid": t["steamid"], "name": t.get("name"), "team": t["team_num"], "x": t.get("X"),
                        "y": t.get("Y"), "yaw": t.get("yaw"), "hp": int(t["health"] or 0) if t.get("health") is not None else 0,
                        "armor": int(t["armor_value"]) if t.get("armor_value") is not None else 0,
                        "weapon": t.get("active_weapon_name"), "money": t.get("balance"),
                        "has_bomb": bool(t.get("inventory") and "C4 Explosive" in t["inventory"]),
                        "alive": bool(t.get("is_alive"))}
                       for t in ticks if t["tick"] == last_tick]
            msg = RoundPrediction(run_id=self.run_id, sequence=frame["sequence"], tick=int(last_tick), round=frame["round"],
                                  p_ct=_clean(p[-1]) if len(p) else None, model_version=self.pred.version,
                                  series=[(int(t), _clean(x)) for t, x in zip(f["tick"], p)], players=players)
            await bus.publish(Topic.ROUND_PREDICTIONS.value, msg.model_dump(mode="json"), key=self.run_id)


class Run:
    """A replay run = streamer + inference + a command listener."""

    def __init__(self, run_id: str, demo_id: str, round_no: int, listen: bool = True):
        self.streamer = ReplayStreamer(run_id, demo_id, round_no)
        self.inference = LiveInference(run_id, demo_id)
        self.run_id = run_id
        self.listen = listen  # False when a runtime service dispatches commands to its runs
        self.tasks: list[asyncio.Task] = []

    async def _commands(self):
        async for cmd in get_bus().subscribe(Topic.SYSTEM_COMMANDS.value, key=self.run_id):
            self.streamer.command(cmd)
            if self.streamer.stopped:
                break

    def start(self):
        self.tasks = [asyncio.create_task(self.inference.run()), asyncio.create_task(self.streamer.run())]
        if self.listen:
            self.tasks.append(asyncio.create_task(self._commands()))
        return self

    def stop(self):
        self.streamer.stopped = True
        for t in self.tasks:
            t.cancel()


async def serve_runtime(idle_timeout: float = 3600.0):
    """Runtime service (stack mode): ONE consumer of system-commands starts/stops runs and routes
    play/pause/seek/speed to them, so a command sent right after START_RUN is never missed (a
    per-run consumer would only see messages produced after it joined). Runs idle for longer than
    ``idle_timeout`` are reaped, in case a gateway died without sending STOP_RUN."""
    bus = get_bus()
    runs: dict[str, Run] = {}
    seen: dict[str, float] = {}
    print("live runtime: waiting for system-commands", flush=True)
    async for raw in bus.subscribe(Topic.SYSTEM_COMMANDS.value):
        try:
            cmd = Command.model_validate(raw)
        except Exception:
            continue
        now = asyncio.get_running_loop().time()
        for rid in [r for r, t in seen.items() if now - t > idle_timeout]:
            runs.pop(rid).stop()
            seen.pop(rid)
        if cmd.type == CommandType.START_RUN:
            if cmd.run_id in runs:
                continue
            try:
                run = await asyncio.to_thread(Run, cmd.run_id, cmd.args["demo_id"], int(cmd.args["round"]), False)
                runs[cmd.run_id] = run.start()
                seen[cmd.run_id] = now
                status, msg = RunStatus.RUNNING, None
            except Exception as e:
                status, msg = RunStatus.FAILED, str(e)
            print(f"run {cmd.run_id}: {status.value} {cmd.args} {msg or ''}", flush=True)
            await bus.publish(Topic.SYSTEM_EVENTS.value, SystemEvent(
                run_id=cmd.run_id, command_id=cmd.command_id, status=status, message=msg,
                ).model_dump(mode="json"), key=cmd.run_id)
        elif cmd.run_id in runs:
            seen[cmd.run_id] = now
            if cmd.type == CommandType.STOP_RUN:
                runs.pop(cmd.run_id).stop()
                seen.pop(cmd.run_id, None)
                print(f"run {cmd.run_id}: stopped", flush=True)
            else:
                runs[cmd.run_id].streamer.command(raw)
