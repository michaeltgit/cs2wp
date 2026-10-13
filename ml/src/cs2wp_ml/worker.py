"""ML worker: claims ``train`` jobs from the shared jobs table (payload {"activate": bool}).
After a version becomes active it queues a ``rescore`` job for the pipeline workers."""

from __future__ import annotations

import os
import socket
import time
import traceback

from cs2wp_core import db, modeling

from .train import train


def run_train_job(job: dict) -> str:
    p = job.get("payload") or {}
    lines: list[str] = []
    version = train(activate=bool(p.get("activate")), cv_models=p.get("cv_models", True), log=lines.append,
                    progress=lambda s: db.update_job(job["id"], stage=s))
    if modeling.registry()["active"] == version:
        db.new_job("rescore", None, {"reason": f"{version} activated"})
    return version


def run_forever(poll: float = 2.0):
    db.init()
    name = f"{socket.gethostname()}:{os.getpid()}:ml"
    print(f"ml worker {name}: kinds=['train']", flush=True)
    while True:
        job = db.claim_job(["train"], name)
        if job is None:
            time.sleep(poll)
            continue
        try:
            db.update_job(job["id"], status="done", stage="done", message=run_train_job(job))
        except Exception:
            db.update_job(job["id"], status="failed", message=traceback.format_exc()[-1500:])
