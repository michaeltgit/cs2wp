"""Durable job queue: inbox watcher, worker claim/run/fail, ingest validation."""

import threading
import time

from cs2wp_core import db
from cs2wp_pipeline import jobs


def setup_module():
    db.init()


def test_inbox_watcher_enqueues_finished_files_once(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(jobs, "enqueue", lambda kind, demo_id=None, **p: seen.append((kind, p["path"], p["cleanup"])))
    (tmp_path / "partial.rar.crdownload").write_bytes(b"x" * 10)  # still downloading: ignore
    (tmp_path / "notes.txt").write_bytes(b"x")                      # not a demo: ignore
    (tmp_path / "match.rar").write_bytes(b"x" * 10)
    stop = threading.Event()
    th = threading.Thread(target=jobs.watch_inbox, args=(stop, 0.05, tmp_path), daemon=True)
    th.start()
    time.sleep(0.4)
    stop.set()
    th.join(1)
    assert seen == [("ingest", str(tmp_path / "match.rar"), True)]


def _wait(jid, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        j = db.rows("SELECT * FROM jobs WHERE id=?", (jid,))[0]
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise TimeoutError(jid)


def test_worker_runs_and_records_failures(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "process_demo", lambda d, job_id=None: calls.append(d))
    w = jobs.Worker(threads=2, poll=0.05)
    w.start()
    try:
        ok = jobs.enqueue("process", "demo-1")
        bad = jobs.enqueue("ingest", path="/nonexistent/x.dem")
        assert _wait(ok)["status"] == "done" and calls == ["demo-1"]
        failed = _wait(bad)
        assert failed["status"] == "failed" and failed["message"]
    finally:
        w.stop.set()


def test_ml_jobs_are_left_for_the_ml_worker():
    jid = jobs.enqueue("train", activate=True)
    assert "train" not in jobs.PIPELINE_KINDS
    while db.claim_job(jobs.PIPELINE_KINDS, "pipeline") is not None:
        pass
    assert db.rows("SELECT status FROM jobs WHERE id=?", (jid,))[0]["status"] == "queued"
