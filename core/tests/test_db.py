import threading

from cs2wp_core import db


def setup_module():
    db.init()


def test_demo_lifecycle():
    db.add_demo("d1", "x-m1-mirage.dem", "sha-1")
    db.add_demo("d1-dup", "copy.dem", "sha-1")  # same file uploaded again: ignored
    assert [r["id"] for r in db.rows("SELECT id FROM demos WHERE sha1=?", ("sha-1",))] == ["d1"]
    db.update_demo("d1", status="ready", score={"ct_side_end": 13, "t_side_end": 9})
    assert db.rows("SELECT status FROM demos WHERE id=?", ("d1",))[0]["status"] == "ready"


def test_jobs_are_claimed_exactly_once():
    ids = {db.new_job("process", f"d{i}", {"i": i}) for i in range(20)}
    got, lock = [], threading.Lock()

    def worker(name):
        while (j := db.claim_job(["process"], name)) is not None:
            with lock:
                got.append(j["id"])

    ts = [threading.Thread(target=worker, args=(f"w{k}",)) for k in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == sorted(ids)  # every job once, none twice


def test_claim_respects_kinds_and_payload():
    jid = db.new_job("train", None, {"activate": True})
    j = db.claim_job(["train"], "ml")
    assert j["id"] == jid and j["payload"] == {"activate": True} and j["status"] == "running"


def test_catalog_round_trip():
    db.add_demo("d2", "y.dem", "sha-2")
    n = db.export_catalog()
    db.delete_demo("d2")
    assert not db.rows("SELECT id FROM demos WHERE id=?", ("d2",))
    assert db.import_catalog() == n
    assert db.rows("SELECT id FROM demos WHERE id=?", ("d2",))
