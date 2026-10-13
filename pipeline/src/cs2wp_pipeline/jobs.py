"""Durable jobs: backend commands (or the inbox watcher, or switching models in the UI) *enqueue* rows in the `jobs` table; pipeline
workers *claim* and run them. Same code on SQLite (lite) and Postgres (stack/RDS).

Job kinds handled here:
    ingest       payload {"key": "uploads/<file>"} (object storage) or {"path": "/abs/path"} (inbox)
    process      demo_id: parse -> features -> score -> Kalshi link
    rescore      re-score every demo with the active model (out-of-sample per match when available)
    kalshi_link  demo_id, payload {"ticker"?, "yes_team"?, "start_ts"?} (auto-find when no ticker)
Training jobs ("train") are claimed by the cs2wp-ml worker.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cs2wp_core import config, db, features, modeling, storage
from cs2wp_core.config import FEATURES as FEAT_DIR
from cs2wp_core.config import INBOX

from . import parse, score

PIPELINE_KINDS = ["ingest", "process", "rescore", "kalshi_link"]


# ---------------- enqueue (used by the API, CLI and watcher) ----------------
def enqueue(kind: str, demo_id: str | None = None, **payload) -> str:
    return db.new_job(kind, demo_id, payload)


# ---------------- job implementations ----------------
def process_demo(demo_id: str, job_id: str | None = None):
    def stage(name):
        if job_id:
            db.update_job(job_id, stage=name)
        db.update_demo(demo_id, status=name)

    try:
        stage("parsing")
        meta = parse.parse_isolated(demo_id)
        stage("features")
        _, ticks, events = parse.load(demo_id)
        build_features(demo_id, meta, ticks, events)
        rounds = meta["rounds"]
        last = rounds[-1]
        final = {"ct_side_end": last["ct_score"] + (last["winner"] == 3),
                 "t_side_end": last["t_score"] + (last["winner"] == 2)}
        db.update_demo(demo_id, map=meta["map"], n_rounds=len(rounds), score=final)
        if modeling.registry()["active"]:
            stage("scoring")
            score.score_demo(demo_id)
            stage("kalshi")
            link_kalshi(demo_id)
            db.update_demo(demo_id, status="ready", error=None)
        else:
            db.update_demo(demo_id, status="needs_model", error=None)
    except Exception as e:
        db.update_demo(demo_id, status="failed", error=str(e)[:500])
        raise


def build_features(demo_id, meta, ticks, events):
    FEAT_DIR.mkdir(parents=True, exist_ok=True)
    features.build(meta, ticks, events, every=1).to_parquet(FEAT_DIR / f"{demo_id}.parquet", index=False)
    storage.publish(f"features/{demo_id}.parquet")


def rebuild_features(job_id: str | None = None) -> int:
    """Features for every processed demo from its stored parse (no re-parsing)."""
    demos = [d["id"] for d in db.rows("SELECT id FROM demos WHERE status IN ('ready','needs_model') ORDER BY id")]
    for i, d in enumerate(demos, 1):
        if job_id:
            db.update_job(job_id, stage=f"features {i}/{len(demos)}")
        meta, ticks, events = parse.load(d)
        build_features(d, meta, ticks, events)
    return len(demos)


def link_kalshi(demo_id: str, ticker: str | None = None, yes_team: str = "a", start_ts: int | None = None) -> str:
    """Link one map to a given market, or (no ticker) auto-link its whole match so every map of it
    points at the same Kalshi match. Records status; never fails the job: most maps have no market
    (Kalshi usually lists only maps 1-2 of a best-of-3)."""
    from . import kalshi
    if ticker:
        try:
            kalshi.link(demo_id, ticker, yes_team, start_ts)
            _record_kalshi(demo_id, "linked")
            return "linked"
        except Exception:
            traceback.print_exc()
            _record_kalshi(demo_id, "failed")
            return "failed"
    return link_match(modeling.match_key(demo_id), also=demo_id).get(demo_id, "no market")


def link_match(key: str, also: str | None = None) -> dict[str, str]:
    """Auto-link every processed map of one match (same archive) to one Kalshi match. `also` is the
    map being processed right now (not marked ready yet, but it belongs in the decision)."""
    from . import kalshi
    ids = [d["id"] for d in db.rows("SELECT id FROM demos WHERE status IN ('ready','needs_model') ORDER BY id")
           if modeling.match_key(d["id"]) == key]
    if also and also not in ids:
        ids = sorted([*ids, also])
    try:
        linked = kalshi.auto_link_match(ids)
        status = "no market"
    except Exception as e:
        linked = {}
        status = "no market" if "no Kalshi" in str(e) or "no team names" in str(e) else "failed"
        if status == "failed":
            traceback.print_exc()
    out = {}
    for d in ids:
        if d in linked:
            _record_kalshi(d, "linked")
        else:
            kalshi.unlink(d)  # drop a stale link from an earlier, different choice
            _record_kalshi(d, status)
        out[d] = "linked" if d in linked else status
    return out


def _record_kalshi(demo_id: str, status: str) -> None:
    from . import kalshi
    if status == "linked":
        info = kalshi.link_info(demo_id)
        db.update_demo(demo_id, kalshi_ticker=info["ticker"], kalshi_status="linked",
                       kalshi_confidence=kalshi.alignment_quality(demo_id).get("confidence"))
    else:
        db.update_demo(demo_id, kalshi_ticker=None, kalshi_status=status, kalshi_confidence=None)


def rescore_all(job_id: str | None = None):
    demos = [d["id"] for d in db.rows("SELECT id FROM demos WHERE status IN ('ready','needs_model')")]
    for i, d in enumerate(demos, 1):
        if job_id:
            db.update_job(job_id, stage=f"rescoring {i}/{len(demos)}")
        score.score_demo(d)
        db.update_demo(d, status="ready")


def ingest_job(job: dict) -> str:
    """Extract an upload/download (can be GBs) and queue a `process` job per map."""
    from . import ingest
    p = job["payload"]
    path = Path(p["path"]) if p.get("path") else storage.local_path(p["key"])
    ids = ingest.ingest(path)
    if not ids:
        raise ValueError("no CS2 demo found in upload")
    todo = [d for d in ids if db.rows("SELECT status FROM demos WHERE id=?", (d,))[0]["status"] != "ready"]
    for d in todo:
        enqueue("process", d)
    if p.get("cleanup"):  # maps are safely stored; the archive is redundant (HLTV keeps the original)
        path.unlink(missing_ok=True)
        if p.get("key") and path.parent.name != "uploads":
            path.parent.rmdir() if not any(path.parent.iterdir()) else None  # uploads/<id>/ folder
        if p.get("key"):
            storage.store().delete(p["key"])
    return f"{len(ids)} map(s): {', '.join(ids)}" + ("" if todo else " (already processed)")


def remove_demo(demo_id: str):
    s = storage.store()
    keys = [f"raw/{demo_id}.dem", f"features/{demo_id}.parquet", f"scores/{demo_id}.parquet",
            f"scores/{demo_id}_events.parquet", f"scores/{demo_id}_wpa.json", f"kalshi/{demo_id}.json",
            f"kalshi/{demo_id}_candles.parquet", f"kalshi/{demo_id}_trades.parquet"]
    keys += [f"parsed/{demo_id}/{f}" for f in ("meta.json", "ticks.parquet", "events.parquet")]
    for k in keys:
        s.delete(k)
    db.delete_demo(demo_id)


def run_job(job: dict) -> str | None:
    kind, demo_id, p = job["kind"], job.get("demo_id"), job.get("payload") or {}
    if kind == "ingest":
        return ingest_job(job)
    if kind == "process":
        process_demo(demo_id, job["id"])
        return None
    if kind == "rescore":
        rescore_all(job["id"])
        return None
    if kind == "kalshi_link":
        return link_kalshi(demo_id, p.get("ticker"), p.get("yes_team", "a"), p.get("start_ts"))
    raise ValueError(f"unknown job kind {kind}")


# ---------------- worker ----------------
class Worker:
    """Claims queued jobs and runs them on a small thread pool (parsing itself runs in a child
    process, so a demoparser2 crash only fails its own job)."""

    def __init__(self, kinds=PIPELINE_KINDS, threads: int = 3, poll: float = 1.0):
        self.kinds, self.threads, self.poll = kinds, threads, poll
        self.name = f"{socket.gethostname()}:{os.getpid()}"
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=threads)
        self.active = 0
        self._lock = threading.Lock()

    def _run(self, job):
        try:
            msg = run_job(job)
            db.update_job(job["id"], status="done", stage="done", message=msg)
        except Exception:
            db.update_job(job["id"], status="failed", message=traceback.format_exc()[-1500:])
        finally:
            with self._lock:
                self.active -= 1

    def loop(self):
        while not self.stop.is_set():
            with self._lock:
                free = self.active < self.threads
            job = db.claim_job(self.kinds, self.name) if free else None
            if job is None:
                self.stop.wait(self.poll)
                continue
            with self._lock:
                self.active += 1
            self.pool.submit(self._run, job)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.loop, daemon=True, name="cs2wp-worker")
        t.start()
        return t


def watch_inbox(stop_event: threading.Event, every: float = 5.0, inbox: Path | None = None):
    """Enqueue finished downloads that appear in the inbox (a browser saves there).
    A file counts as finished when it is not a .crdownload and its size held for one interval."""
    from .ingest import ARCHIVES
    inbox = inbox or INBOX
    seen_size: dict[str, int] = {}
    submitted: set[str] = set()
    while not stop_event.wait(every):
        for f in inbox.iterdir():
            if not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in ARCHIVES | {".dem"}:
                continue
            key = str(f)
            if key in submitted:
                continue
            size = f.stat().st_size
            if seen_size.get(key) == size and size > 0:
                submitted.add(key)
                enqueue("ingest", path=str(f), cleanup=True)
            seen_size[key] = size


def queue_new_uploads() -> int:
    """Queue an ingest job for every archive in storage uploads/ that has no job yet. uploads/ is a
    folder locally and the demo bucket on S3, so the HLTV downloader and a manual
    `aws s3 cp file s3://<bucket>/uploads/` both end up here. Files appear there only once complete."""
    from .ingest import ARCHIVES
    n = 0
    for key in storage.store().list("uploads/"):
        name = key.rsplit("/", 1)[-1]
        if name.startswith(".") or Path(name).suffix.lower() not in ARCHIVES | {".dem"}:
            continue
        if db.rows("SELECT id FROM jobs WHERE kind='ingest' AND payload LIKE ? LIMIT 1", (f'%"{key}"%',)):
            continue  # already queued, running, done or failed (failed ones are left for an operator)
        enqueue("ingest", key=key, cleanup=True)
        n += 1
    if storage.store().kind == "local":  # tidy folders emptied by finished ingests
        for d in sorted((config.DATA / "uploads").glob("*/"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    return n


def watch_uploads(stop_event: threading.Event, every: float = 30.0):
    while not stop_event.wait(every):
        try:
            queue_new_uploads()
        except Exception:  # storage briefly unreachable: try again next round
            traceback.print_exc()


def run_forever(threads: int = 3, watch: bool = True):
    db.init()
    w = Worker(threads=threads)
    w.start()
    stop = threading.Event()
    if watch:
        threading.Thread(target=watch_inbox, args=(stop,), daemon=True, name="cs2wp-inbox").start()
    threading.Thread(target=watch_uploads, args=(stop,), daemon=True, name="cs2wp-uploads").start()
    print(f"pipeline worker {w.name}: kinds={w.kinds} threads={threads} inbox={'on' if watch else 'off'} "
          "uploads=on", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        w.stop.set()
        stop.set()
