"""HLTV demo acquisition (the reference design's "Downloader Worker").

discover  read HLTV's starred results (newest first, 100 per page) back to a cut-off date and record
          each match in the ``downloads`` table as pending
download  for each pending match, newest first: skip it if we already have its archive, otherwise
          download the demo archive into storage ``uploads/`` (a folder locally, the S3 bucket on AWS).
          The uploads watcher then queues the normal ingest job (dedupe, parse, score, Kalshi link).

HLTV is behind Cloudflare: plain HTTP clients get a challenge page, so requests go through
curl_cffi impersonating Chrome. Requests are spaced out (CS2WP_HLTV_DELAY seconds, default 4) and
one download runs at a time; if HLTV starts challenging, the run stops instead of hammering it.
Check HLTV's terms before running it at scale.
"""

from __future__ import annotations

import html
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from cs2wp_core import config, db, storage

BASE = "https://www.hltv.org"
PAGE = 100
DELAY = float(os.environ.get("CS2WP_HLTV_DELAY", "4"))
CS2_START = "2023-10-01"  # older matches are CS:GO demos, which the CS2 parser cannot read
MAGIC = (b"Rar!", b"PK\x03\x04", b"7z\xbc\xaf", b"PBDEMS2", b"BZh", b"\x1f\x8b")


class Blocked(RuntimeError):
    """HLTV answered with a Cloudflare challenge: stop and try again later (or from another machine)."""


def session():
    from curl_cffi import requests  # Chrome TLS/HTTP fingerprint; plain clients are challenged
    return requests.Session(impersonate="chrome")


def _check(r, url):
    if r.status_code in (403, 429, 503) and (r.headers.get("cf-mitigated") or "Just a moment" in r.text[:3000]):
        raise Blocked(f"Cloudflare challenge on {url} ({r.status_code})")
    r.raise_for_status()
    return r


def _get(s, url, **kw):
    return _check(s.get(url, timeout=60, **kw), url)


# ---------------- parsing ----------------
_RESULT = re.compile(r'<div class="result-con[^"]*" data-zonedgrouping-entry-unix="(\d+)">(.*?)</table>', re.S)


def parse_results(page: str) -> list[dict]:
    """Matches on one HLTV results page (featured block included; duplicates removed)."""
    out, seen = [], set()
    for unix, block in _RESULT.findall(page):
        m = re.search(r'href="/matches/(\d+)/([^"]+)"', block)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        teams = [html.unescape(t).strip() for t in re.findall(r'<div class="team[^"]*">([^<]+)</div>', block)]
        score = re.search(r'<td class="result-score">\s*<span[^>]*>(\d+)</span>\s*-\s*<span[^>]*>(\d+)</span>', block)
        event = re.search(r'<span class="event-name">([^<]+)</span>', block)
        out.append({"match_id": m.group(1), "url": f"{BASE}/matches/{m.group(1)}/{m.group(2)}",
                    "team1": teams[0] if teams else None, "team2": teams[1] if len(teams) > 1 else None,
                    "score": f"{score.group(1)}-{score.group(2)}" if score else None,
                    "event": html.unescape(event.group(1)).strip() if event else None,
                    "match_ts": int(unix) / 1000})
    return out


def parse_demo_link(page: str) -> str | None:
    m = re.search(r'href="(/download/demo/\d+)"', page)
    return BASE + m.group(1) if m else None


# ---------------- discover ----------------
def discover(pages: int = 1, since: str = CS2_START, stars: int = 1, s=None, log=print) -> int:
    """Record starred matches from the newest results back to `since` (or `pages` pages)."""
    s = s or session()
    cutoff = datetime.fromisoformat(since).replace(tzinfo=UTC).timestamp()
    new = 0
    for i in range(pages):
        url = f"{BASE}/results?stars={stars}&offset={i * PAGE}"
        found = parse_results(_get(s, url).text)
        keep = [f for f in found if f["match_ts"] >= cutoff]
        new += db.add_downloads(keep)
        log(f"results page {i + 1}: {len(found)} matches, {len(keep)} since {since}, {new} new so far")
        if not found or len(keep) < len(found):
            break  # past the cut-off (or the end of the list)
        time.sleep(DELAY)
    return new


# ---------------- download ----------------
def _have(archive: str) -> bool:
    """Do we already have demos from this HLTV archive? (our demo file names contain its name)"""
    stem = Path(archive).stem
    return bool(db.rows("SELECT id FROM demos WHERE filename LIKE ? LIMIT 1", (f"%{stem}%",)))


def download_one(row: dict, s, log=print) -> str:
    mid = row["match_id"]
    page = _get(s, row["url"]).text
    link = parse_demo_link(page)
    if not link:
        db.update_download(mid, status="no_demo")
        return "no_demo"
    time.sleep(DELAY)
    head = _check(s.get(link, timeout=60, allow_redirects=False, headers={"Referer": row["url"]}), link)
    target = head.headers.get("location") or link
    archive = re.sub(r"[^A-Za-z0-9._-]", "_", Path(target.split("?")[0]).name) or f"hltv-{mid}.rar"
    if _have(archive):
        db.update_download(mid, status="have", archive=archive)
        return "have"
    tmp = config.CACHE / "downloads" / f"{mid}.part"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    r = _check(s.get(link, timeout=1800, stream=True, headers={"Referer": row["url"]}), link)
    size = 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            size += len(chunk)
    with open(tmp, "rb") as f:
        head_bytes = f.read(8)
    if not head_bytes.startswith(MAGIC):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"not a demo archive (starts with {head_bytes!r})")
    key = f"uploads/hltv-{mid}/{archive}"
    dest = storage.local_path(key, fetch=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, dest)  # appears in uploads/ only once complete
    storage.publish(key)
    if storage.store().kind != "local":
        dest.unlink(missing_ok=True)  # the bucket holds it now; don't keep a second copy on this disk
    db.update_download(mid, status="done", archive=archive, key=key, bytes=size, error=None)
    log(f"downloaded {archive} ({size / 1e6:.0f} MB) -> {key}")
    return "done"


def download(limit: int | None = None, max_gb: float | None = None, s=None, log=print) -> dict:
    """Work through pending matches, newest first, one at a time. Stops early when HLTV challenges."""
    s = s or session()
    counts: dict[str, int] = {}
    total = 0
    for row in db.pending_downloads(limit):
        if max_gb is not None and total / 1e9 >= max_gb:
            log(f"stopping: {total / 1e9:.1f} GB downloaded (max {max_gb} GB)")
            break
        try:
            status = download_one(row, s, log)
        except Blocked as e:
            log(f"stopping: {e}")
            counts["blocked"] = 1
            break
        except Exception as e:  # one bad match must not stop the run
            db.update_download(row["match_id"], status="failed", error=str(e)[:500], attempts=(row.get("attempts") or 0) + 1)
            status = "failed"
            log(f"failed {row['match_id']} ({row.get('team1')} vs {row.get('team2')}): {e}")
        counts[status] = counts.get(status, 0) + 1
        if status == "done":
            total += db.rows("SELECT bytes FROM downloads WHERE match_id=?", (row["match_id"],))[0]["bytes"] or 0
        time.sleep(DELAY)
    return counts


def sync(pages: int, limit: int | None, max_gb: float | None, since: str = CS2_START, every_hours: float = 0,
         log=print) -> None:
    """discover + download, once or every `every_hours` (the downloader service)."""
    while True:
        s = session()
        try:
            discover(pages, since, s=s, log=log)
            log(f"download: {download(limit, max_gb, s=s, log=log)}")
        except Blocked as e:
            log(f"blocked: {e}")
        if not every_hours:
            return
        time.sleep(every_hours * 3600)
