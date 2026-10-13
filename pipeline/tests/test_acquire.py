"""HLTV acquisition with a fake HTTP session (no network): parsing, the downloads table, skipping
archives we already have, downloads landing in storage uploads/, and the uploads watcher."""

import pytest

from cs2wp_core import db, storage
from cs2wp_pipeline import acquire, jobs

RESULTS = """<div class="results-all"><div class="results-sublist">
<div class="result-con " data-zonedgrouping-entry-unix="1791818316000"><a href="/matches/900001/alpha-vs-beta-cup" class="a-reset">
<div class="result"><table><tr><td class="team-cell"><div class="line-align team1"><div class="team ">Alpha</div></div></td>
<td class="result-score"><span class="score-lost">0</span> - <span class="score-won">2</span></td>
<td class="team-cell"><div class="line-align team2"><div class="team team-won">Beta &amp; Co</div></div></td>
<td class="event"><span class="event-name">Test Cup 2026</span></td></tr></table></div></a></div>
<div class="result-con " data-zonedgrouping-entry-unix="1600000000000"><a href="/matches/900002/old-csgo-match" class="a-reset">
<div class="result"><table><tr><td><div class="team ">Old</div></td><td><div class="team ">Timers</div></td></tr></table></div></a></div>
</div></div>"""
MATCH = '<a class="stream-box" href="/download/demo/555"><span>GOTV Demo</span></a>'
ARCHIVE = b"Rar!\x1a\x07\x01\x00" + b"x" * 1000


class Resp:
    def __init__(self, status=200, text="", headers=None, body=b""):
        self.status_code, self.text, self.headers, self.body = status, text, headers or {}, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, chunk_size=1):
        yield self.body


class FakeHLTV:
    def __init__(self, archive_name="test-cup-2026-alpha-vs-beta-bo3-AbC123.rar", demo_page=MATCH, challenge=False):
        self.archive_name, self.demo_page, self.challenge, self.calls = archive_name, demo_page, challenge, []

    def get(self, url, timeout=None, allow_redirects=True, stream=False, headers=None):
        self.calls.append(url)
        if self.challenge:
            return Resp(403, "<title>Just a moment...</title>", {"cf-mitigated": "challenge"})
        if "/results" in url:
            return Resp(text=RESULTS)
        if "/matches/" in url:
            return Resp(text=self.demo_page)
        if "/download/demo/" in url and not allow_redirects:
            return Resp(302, headers={"location": f"https://r2-demos.hltv.org/demos/1/{self.archive_name}"})
        return Resp(body=ARCHIVE)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    db.init()
    db.execute("DELETE FROM downloads")
    db.execute("DELETE FROM jobs")
    monkeypatch.setattr(acquire, "DELAY", 0)


def test_parse_results_and_demo_link():
    rows = acquire.parse_results(RESULTS)
    assert rows[0] == {"match_id": "900001", "url": "https://www.hltv.org/matches/900001/alpha-vs-beta-cup",
                       "team1": "Alpha", "team2": "Beta & Co", "score": "0-2", "event": "Test Cup 2026",
                       "match_ts": 1791818316.0}
    assert acquire.parse_demo_link(MATCH) == "https://www.hltv.org/download/demo/555"
    assert acquire.parse_demo_link("<html>no demo</html>") is None


def test_discover_stops_at_the_cs2_cutoff():
    assert acquire.discover(pages=5, s=FakeHLTV(), log=lambda *_: None) == 1  # the 2020 match is CS:GO
    assert [r["match_id"] for r in db.pending_downloads()] == ["900001"]
    assert acquire.discover(pages=5, s=FakeHLTV(), log=lambda *_: None) == 0  # known matches are not re-added


def test_download_lands_in_uploads_and_is_queued_once():
    acquire.discover(s=FakeHLTV(), log=lambda *_: None)
    assert acquire.download(s=FakeHLTV(), log=lambda *_: None) == {"done": 1}
    key = "uploads/hltv-900001/test-cup-2026-alpha-vs-beta-bo3-AbC123.rar"
    assert storage.local_path(key).read_bytes() == ARCHIVE
    row = db.rows("SELECT status, key, bytes FROM downloads WHERE match_id='900001'")[0]
    assert row == {"status": "done", "key": key, "bytes": len(ARCHIVE)}
    assert jobs.queue_new_uploads() == 1 and jobs.queue_new_uploads() == 0  # one ingest job per file
    assert db.rows("SELECT kind FROM jobs")[0]["kind"] == "ingest"
    storage.store().delete(key)


def test_archives_we_already_have_are_not_downloaded(monkeypatch):
    db.add_demo("have-it", "test-cup-2026-alpha-vs-beta-bo3-AbC123-alpha-vs-beta-m1-mirage.dem", "sha-have")
    acquire.discover(s=FakeHLTV(), log=lambda *_: None)
    fake = FakeHLTV()
    assert acquire.download(s=fake, log=lambda *_: None) == {"have": 1}
    assert not any(u.endswith(".rar") or "r2-demos" in u for u in fake.calls)
    db.delete_demo("have-it")


def test_no_demo_and_blocked():
    acquire.discover(s=FakeHLTV(), log=lambda *_: None)
    assert acquire.download(s=FakeHLTV(demo_page="<html></html>"), log=lambda *_: None) == {"no_demo": 1}
    db.update_download("900001", status="pending")
    assert acquire.download(s=FakeHLTV(challenge=True), log=lambda *_: None) == {"blocked": 1}
    assert db.pending_downloads()[0]["status"] == "pending"  # left for a later run, not marked failed
