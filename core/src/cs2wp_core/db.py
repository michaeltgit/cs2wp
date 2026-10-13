"""Metadata store: SQLite locally, PostgreSQL (RDS) in the stack. SQLAlchemy Core underneath.

Callers write plain SQL with ``?`` placeholders (portable subset); they are rewritten to named
parameters for SQLAlchemy. Jobs are claimed atomically (``FOR UPDATE SKIP LOCKED`` on Postgres),
which is the durable job queue the control plane is built on.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from functools import lru_cache

import sqlalchemy as sa

from . import config

metadata = sa.MetaData()

demos = sa.Table(
    "demos", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("filename", sa.Text),
    sa.Column("sha1", sa.Text, unique=True),
    sa.Column("map", sa.Text),
    sa.Column("status", sa.Text),
    sa.Column("error", sa.Text),
    sa.Column("n_rounds", sa.Integer),
    sa.Column("score", sa.Text),
    sa.Column("created_at", sa.Float(53)),
    sa.Column("kalshi_ticker", sa.Text),
    sa.Column("kalshi_status", sa.Text),
    sa.Column("kalshi_confidence", sa.Text),
    sa.Column("score_model", sa.Text),
    sa.Column("score_kind", sa.Text),
)

jobs = sa.Table(
    "jobs", metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("demo_id", sa.Text),
    sa.Column("kind", sa.Text),           # ingest | process | rescore | kalshi_link | train | ...
    sa.Column("status", sa.Text),         # queued | running | done | failed
    sa.Column("stage", sa.Text),
    sa.Column("message", sa.Text),
    sa.Column("payload", sa.Text),        # JSON arguments
    sa.Column("worker", sa.Text),
    sa.Column("attempts", sa.Integer, server_default="0"),
    sa.Column("created_at", sa.Float(53)),
    sa.Column("updated_at", sa.Float(53)),
)

# HLTV matches found by the downloader (pipeline/acquire.py) and what happened to each
downloads = sa.Table(
    "downloads", metadata,
    sa.Column("match_id", sa.Text, primary_key=True),  # HLTV match id
    sa.Column("url", sa.Text),
    sa.Column("event", sa.Text),
    sa.Column("team1", sa.Text),
    sa.Column("team2", sa.Text),
    sa.Column("score", sa.Text),
    sa.Column("match_ts", sa.Float(53)),
    sa.Column("status", sa.Text),         # pending | done | have | no_demo | failed
    sa.Column("archive", sa.Text),        # HLTV archive file name
    sa.Column("key", sa.Text),            # where it was stored (uploads/...)
    sa.Column("bytes", sa.BigInteger),
    sa.Column("error", sa.Text),
    sa.Column("attempts", sa.Integer, server_default="0"),
    sa.Column("created_at", sa.Float(53)),
    sa.Column("updated_at", sa.Float(53)),
)

_lock = threading.Lock()


@lru_cache(maxsize=1)
def engine() -> sa.Engine:
    url = config.DATABASE_URL
    kw = {"future": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kw["pool_pre_ping"] = True
    return sa.create_engine(url, **kw)


def is_postgres() -> bool:
    return engine().dialect.name == "postgresql"


def init() -> None:
    metadata.create_all(engine())
    # forward-compatible column additions for databases created by older versions
    insp = sa.inspect(engine())
    for table in (demos, jobs):
        have = {c["name"] for c in insp.get_columns(table.name)}
        with engine().begin() as c:
            for col in table.columns:
                if col.name not in have:
                    c.execute(sa.text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} '
                                      f'{col.type.compile(engine().dialect)}'))


def _named(sql: str, args) -> tuple[str, dict]:
    params, i = {}, 0

    def sub(_):
        nonlocal i
        name = f"p{i}"
        params[name] = args[i]
        i += 1
        return f":{name}"
    return re.sub(r"\?", sub, sql), params


def rows(sql: str, args=()) -> list[dict]:
    q, p = _named(sql, args)
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(sa.text(q), p)]


def execute(sql: str, args=()) -> None:
    q, p = _named(sql, args)
    with _lock, engine().begin() as c:
        c.execute(sa.text(q), p)


# ---------------- demos ----------------
def add_demo(demo_id, filename, sha1):
    with _lock, engine().begin() as c:
        exists = c.execute(sa.select(demos.c.id).where(
            sa.or_(demos.c.id == demo_id, demos.c.sha1 == sha1))).first()
        if not exists:
            c.execute(demos.insert().values(id=demo_id, filename=filename, sha1=sha1, status="new",
                                            created_at=time.time()))


def demo_by_sha1(sha1):
    r = rows("SELECT * FROM demos WHERE sha1=?", (sha1,))
    return r[0] if r else None


def update_demo(demo_id, **fields):
    if "score" in fields and not isinstance(fields["score"], (str, type(None))):
        fields["score"] = json.dumps(fields["score"])
    with _lock, engine().begin() as c:
        c.execute(demos.update().where(demos.c.id == demo_id).values(**fields))


def delete_demo(demo_id):
    with _lock, engine().begin() as c:
        c.execute(demos.delete().where(demos.c.id == demo_id))
        c.execute(jobs.delete().where(jobs.c.demo_id == demo_id))


# ---------------- jobs (durable queue) ----------------
def new_job(kind, demo_id=None, payload: dict | None = None) -> str:
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    with _lock, engine().begin() as c:
        c.execute(jobs.insert().values(id=jid, demo_id=demo_id, kind=kind, status="queued",
                                       payload=json.dumps(payload or {}), attempts=0,
                                       created_at=now, updated_at=now))
    return jid


def update_job(jid, **fields):
    fields["updated_at"] = time.time()
    with _lock, engine().begin() as c:
        c.execute(jobs.update().where(jobs.c.id == jid).values(**fields))


def claim_job(kinds: list[str], worker: str) -> dict | None:
    """Atomically move the oldest queued job of one of `kinds` to running and return it."""
    now = time.time()
    with _lock, engine().begin() as c:
        q = (sa.select(jobs).where(jobs.c.status == "queued", jobs.c.kind.in_(kinds))
             .order_by(jobs.c.created_at).limit(1))
        if is_postgres():
            q = q.with_for_update(skip_locked=True)
        row = c.execute(q).first()
        if row is None:
            return None
        c.execute(jobs.update().where(jobs.c.id == row.id, jobs.c.status == "queued").values(
            status="running", worker=worker, attempts=(row.attempts or 0) + 1, updated_at=now))
        job = {**row._mapping, "status": "running", "worker": worker, "attempts": (row.attempts or 0) + 1}
        job["payload"] = json.loads(job.get("payload") or "{}")
        return job


# ---------------- downloads (HLTV acquisition) ----------------
def add_downloads(found: list[dict]) -> int:
    """Record newly discovered matches as pending; matches already known keep their status."""
    now, n = time.time(), 0
    with _lock, engine().begin() as c:
        for r in found:
            if c.execute(sa.select(downloads.c.match_id).where(downloads.c.match_id == r["match_id"])).first():
                continue
            c.execute(downloads.insert().values(**r, status="pending", attempts=0, created_at=now, updated_at=now))
            n += 1
    return n


def pending_downloads(limit: int | None = None, max_attempts: int = 3) -> list[dict]:
    """Newest first: pending ones, and failed ones that have retries left."""
    q = (sa.select(downloads).where(sa.or_(downloads.c.status == "pending",
                                            sa.and_(downloads.c.status == "failed", downloads.c.attempts < max_attempts)))
         .order_by(downloads.c.match_ts.desc()))
    if limit:
        q = q.limit(limit)
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def update_download(match_id: str, **fields) -> None:
    fields["updated_at"] = time.time()
    with _lock, engine().begin() as c:
        c.execute(downloads.update().where(downloads.c.match_id == match_id).values(**fields))


# ---------------- catalog (portable snapshot of the demos table) ----------------
CATALOG_KEY = "catalog/demos.json"


def export_catalog() -> int:
    """Write the demos table to object storage, so a fresh database (another laptop, Postgres in
    the stack, RDS) can be rebuilt from storage alone with ``import_catalog``."""
    from . import storage
    rows_ = rows("SELECT * FROM demos ORDER BY created_at")
    p = storage.local_path(CATALOG_KEY, fetch=False)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows_, indent=0, default=str))
    storage.publish(CATALOG_KEY)
    return len(rows_)


def import_catalog() -> int:
    """Upsert demos from ``catalog/demos.json`` in object storage."""
    from . import storage
    p = storage.local_path(CATALOG_KEY)
    if not p.exists():
        raise FileNotFoundError(CATALOG_KEY)
    cols = {c.name for c in demos.columns}
    n = 0
    with _lock, engine().begin() as c:
        for r in json.loads(p.read_text()):
            r = {k: v for k, v in r.items() if k in cols}
            c.execute(demos.delete().where(sa.or_(demos.c.id == r["id"], demos.c.sha1 == r.get("sha1"))))
            c.execute(demos.insert().values(**r))
            n += 1
    return n
