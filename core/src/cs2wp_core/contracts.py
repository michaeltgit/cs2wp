"""Versioned data contracts shared by every service.

Bump SCHEMA_VERSION on any breaking change; consumers reject messages with a newer major version.
These are the contracts named in the architecture: canonical game state (RawGS), round
predictions, map evidence, market quotes, and the control plane's commands/events.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class Topic(str, Enum):
    RAW_GS = "raw-gs"
    UI_GAME_STATE = "ui-game-state"
    ROUND_PREDICTIONS = "round-predictions"
    MAP_EVIDENCE = "map-evidence"
    MARKET_QUOTES = "market-quotes"
    SYSTEM_COMMANDS = "system-commands"
    SYSTEM_EVENTS = "system-events"


class _Msg(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    sequence: int = 0
    produced_at: float = Field(default_factory=time.time)


class PlayerState(BaseModel):
    """One player at one tick (subset of the 64 Hz parquet columns)."""
    steamid: str
    name: str | None = None
    team_num: int
    X: float | None = None
    Y: float | None = None
    Z: float | None = None
    yaw: float | None = None
    is_alive: bool | None = None
    health: float | None = None
    armor_value: float | None = None
    has_helmet: bool | None = None
    has_defuser: bool | None = None
    current_equip_value: float | None = None
    balance: float | None = None
    inventory: list[str] | None = None
    active_weapon_name: str | None = None
    is_defusing: bool | None = None
    flash_duration: float | None = None
    is_bomb_planted: bool | None = None
    is_bomb_dropped: bool | None = None
    in_bomb_zone: bool | None = None
    last_place_name: str | None = None
    game_time: float | None = None
    round_start_time: float | None = None


class RawGSFrame(_Msg):
    """Canonical game state for a batch of consecutive ticks of one round.

    Replay and GRID adapters both emit this; consumers never branch on `source`.
    `round_meta` carries the round context (freeze_end, scores, sides) so state can be rebuilt
    from any frame (the round checkpoint)."""
    source: Literal["replay", "grid"] = "replay"
    demo_id: str | None = None
    map: str | None = None
    round: int
    ticks: list[dict[str, Any]]          # PlayerState-shaped rows, one per player per tick
    events: list[dict[str, Any]] = []    # kills, plants, defuses ... with tick <= last tick
    round_meta: dict[str, Any]


class RoundPrediction(_Msg):
    tick: int
    round: int
    p_ct: float | None
    model_version: str
    series: list[tuple[int, float | None]] = []   # (tick, p_ct) for every tick in the frame
    players: list[dict[str, Any]] = []            # display projection for the radar


class MapEvidence(_Msg):
    tick: int
    round: int
    p_map_a: float
    a_score: int
    b_score: int
    model_version: str


class MarketQuote(_Msg):
    ticker: str
    ts: float
    yes_bid: float | None = None
    yes_ask: float | None = None
    last: float | None = None
    size: float | None = None


class CommandType(str, Enum):
    START_RUN = "start_run"
    PLAY = "play"
    PAUSE = "pause"
    SEEK = "seek"
    SPEED = "speed"
    STOP_RUN = "stop_run"


class Command(_Msg):
    command_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: CommandType
    args: dict[str, Any] = {}


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SystemEvent(_Msg):
    command_id: str | None = None
    status: RunStatus
    message: str | None = None
