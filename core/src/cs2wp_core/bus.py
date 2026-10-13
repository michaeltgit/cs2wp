"""Message bus for the live runtime: in-process (one process, dev) or Kafka (stack / production).

Same API either way:

    bus = get_bus()
    await bus.publish(topic, msg_dict, key=run_id)
    async for msg in bus.subscribe(topic, key=run_id): ...

Messages are JSON dicts that follow the contracts in ``cs2wp_core.contracts``. With Kafka every
topic is partitioned by ``key`` (the run_id), so all messages of one run stay ordered.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from . import config


class InProcessBus:
    """asyncio queues; slow consumers drop the oldest message (live data conflates)."""

    def __init__(self):
        self.subs: dict[tuple[str, str | None], list[asyncio.Queue]] = {}

    async def publish(self, topic: str, msg: dict, key: str | None = None) -> None:
        for k in ((topic, key), (topic, None)) if key is not None else ((topic, None),):
            for q in self.subs.get(k, []):
                if q.full():
                    q.get_nowait()
                await q.put(msg)

    async def subscribe(self, topic: str, key: str | None = None) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.subs.setdefault((topic, key), []).append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.subs[(topic, key)].remove(q)

    async def close(self):
        return None


class KafkaBus:
    """aiokafka producer/consumers. Consumers read from 'latest' and filter by key."""

    def __init__(self, bootstrap: str = config.KAFKA_BOOTSTRAP):
        self.bootstrap = bootstrap
        self._producer = None

    async def _prod(self):
        if self._producer is None:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap,
                                              value_serializer=lambda v: json.dumps(v, default=str).encode(),
                                              key_serializer=lambda k: k.encode() if k else None,
                                              linger_ms=5)
            await self._producer.start()
        return self._producer

    async def publish(self, topic: str, msg: dict, key: str | None = None) -> None:
        p = await self._prod()
        await p.send(topic, msg, key=key)

    async def subscribe(self, topic: str, key: str | None = None) -> AsyncIterator[dict]:
        from aiokafka import AIOKafkaConsumer
        c = AIOKafkaConsumer(topic, bootstrap_servers=self.bootstrap, auto_offset_reset="latest",
                             enable_auto_commit=False, group_id=None,
                             value_deserializer=lambda v: json.loads(v))
        await c.start()
        try:
            async for m in c:
                if key is None or (m.key and m.key.decode() == key):
                    yield m.value
        finally:
            await c.stop()

    async def close(self):
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None


_BUS = None


def get_bus():
    global _BUS
    if _BUS is None:
        _BUS = KafkaBus() if config.BUS == "kafka" else InProcessBus()
    return _BUS


async def wait_forever():
    await asyncio.Event().wait()
