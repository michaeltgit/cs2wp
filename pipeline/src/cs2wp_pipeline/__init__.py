"""cs2wp-pipeline: Linux workers (ingest, parse, features, score, Kalshi, live runtime)."""

import argparse
import sys

__version__ = "0.1.0"


def main(argv=None):
    from cs2wp_core import db

    ap = argparse.ArgumentParser(prog="cs2wp-pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_w = sub.add_parser("worker", help="claim + run pipeline jobs; watch the inbox for downloads")
    p_w.add_argument("--threads", type=int, default=3)
    p_w.add_argument("--no-inbox", action="store_true")
    sub.add_parser("runtime", help="live runtime: start/stop replay runs from system-commands (Kafka mode)")
    p_in = sub.add_parser("ingest", help="ingest .dem/.rar/.zip files or folders now (default: data/inbox)")
    p_in.add_argument("paths", nargs="*")
    p_pr = sub.add_parser("process", help="(re)process demos now: parse+features+score(+Kalshi), in this process")
    p_pr.add_argument("--all", action="store_true", help="also reprocess demos that are ready")
    p_pr.add_argument("ids", nargs="*")
    p_q = sub.add_parser("enqueue", help="queue a job for the workers")
    p_q.add_argument("kind", choices=["process", "rescore", "kalshi_link"])
    p_q.add_argument("demo_id", nargs="?")
    sub.add_parser("rescore", help="rescore every demo now (out-of-sample per match when available)")
    p_hd = sub.add_parser("hltv-discover", help="record HLTV starred matches (newest first) as pending downloads")
    p_hd.add_argument("--pages", type=int, default=1, help="results pages of 100 (stops earlier at --since)")
    p_hd.add_argument("--since", default="2023-10-01", help="cut-off date (CS2 demos start autumn 2023)")
    p_dl = sub.add_parser("hltv-download", help="download pending HLTV demos into uploads/ (newest first)")
    p_dl.add_argument("--limit", type=int, help="at most N matches this run")
    p_dl.add_argument("--max-gb", type=float, help="stop after this many GB")
    p_hs = sub.add_parser("hltv-sync", help="discover + download; with --every-hours keeps running (downloader service)")
    p_hs.add_argument("--pages", type=int, default=1)
    p_hs.add_argument("--since", default="2023-10-01")
    p_hs.add_argument("--limit", type=int)
    p_hs.add_argument("--max-gb", type=float)
    p_hs.add_argument("--every-hours", type=float, default=0)
    sub.add_parser("hltv-status", help="downloads by status")
    sub.add_parser("features", help="rebuild features for every demo from its parsed data (after changing feature code)")
    p_vl = sub.add_parser("validate-live", help="validation gate: live replay path == batch scoring (features + P)")
    p_vl.add_argument("ids", nargs="*", help="demo ids (default: every ready demo)")
    p_vl.add_argument("--rounds", type=int, default=0, help="only the first N rounds of each demo (0 = all)")
    p_kl = sub.add_parser("kalshi-link", help="link one map to Kalshi: auto-find, or a given market")
    p_kl.add_argument("demo_id")
    p_kl.add_argument("--ticker", help="Kalshi market ticker (default: auto-find)")
    p_kl.add_argument("--yes", choices=["a", "b"], default="a", help="which of our teams YES pays on")
    p_kl.add_argument("--start", type=int, help="unix time of round 1 (default: align on trades)")
    p_ka = sub.add_parser("kalshi-all", help="link every map to Kalshi and print the comparison")
    p_ka.add_argument("--relink", action="store_true")
    sub.add_parser("kalshi-realign", help="re-fit every link's start time from its stored trades (offline)")
    sub.add_parser("sites", help="relearn bomb-site centres (print JSON for core/src/cs2wp_core/sites.json)")
    p_rm = sub.add_parser("remove", help="delete demos and all derived data")
    p_rm.add_argument("ids", nargs="+")
    p_pub = sub.add_parser("publish-all", help="upload every local artifact to object storage (local -> S3)")
    p_pub.add_argument("--skip-raw", action="store_true", help="leave raw .dem files out (they are GBs)")
    sub.add_parser("status", help="demo counts by status")
    sub.add_parser("catalog-export", help="snapshot the demos table to catalog/demos.json in storage")
    sub.add_parser("catalog-import", help="load catalog/demos.json from storage into this database")
    a = ap.parse_args(argv)
    db.init()

    if a.cmd == "worker":
        from .jobs import run_forever
        run_forever(threads=a.threads, watch=not a.no_inbox)
    elif a.cmd == "runtime":
        import asyncio

        from .runtime import serve_runtime
        asyncio.run(serve_runtime())
    elif a.cmd == "ingest":
        from cs2wp_core.config import INBOX

        from . import ingest
        ids = [d for p in (a.paths or [str(INBOX)]) for d in ingest.ingest(p)]
        print(f"{len(ids)} demos: {ids}")
    elif a.cmd == "process":
        from .jobs import process_demo
        q = "SELECT id FROM demos" + ("" if a.all else " WHERE status NOT IN ('ready')")
        todo = a.ids or [d["id"] for d in db.rows(q)]
        for i, d in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {d}", flush=True)
            try:
                process_demo(d)
            except Exception as e:
                print(f"  failed: {e}", file=sys.stderr)
    elif a.cmd == "enqueue":
        from .jobs import enqueue
        print(enqueue(a.kind, a.demo_id))
    elif a.cmd == "rescore":
        from .jobs import rescore_all
        rescore_all()
    elif a.cmd == "hltv-discover":
        from . import acquire
        print(f"{acquire.discover(a.pages, a.since)} new matches recorded")
    elif a.cmd == "hltv-download":
        from . import acquire
        print(acquire.download(a.limit, a.max_gb))
    elif a.cmd == "hltv-sync":
        from . import acquire
        acquire.sync(a.pages, a.limit, a.max_gb, a.since, a.every_hours)
    elif a.cmd == "hltv-status":
        for r in db.rows("SELECT status, COUNT(*) AS n, SUM(bytes) AS b FROM downloads GROUP BY status ORDER BY status"):
            print(f"{r['status']:10s} {int(r['n']):6d}  {float(r['b'] or 0) / 1e9:7.1f} GB")
    elif a.cmd == "features":
        from .jobs import rebuild_features
        print(f"rebuilt features for {rebuild_features()} demos; retrain (cs2wp-ml train --activate) to use them")
    elif a.cmd == "validate-live":
        from .validate import live_vs_batch
        ids = a.ids or [r["id"] for r in db.rows("SELECT id FROM demos WHERE status='ready' ORDER BY id")]
        failed = 0
        for d in ids:
            from .parse import load_meta
            rounds = [r["round"] for r in load_meta(d)["rounds"]][: a.rounds or None]
            r = live_vs_batch(d, rounds)
            failed += not r["ok"]
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {d[:60]}  {r['ticks_compared']} ticks  "
                  f"max |dfeature| {r['max_feature_diff']:.2e}  max |dP| {r['max_p_diff']:.2e}  ({r['model']})")
            for m in r["mismatches"]:
                print("     ", m)
        raise SystemExit(1 if failed else 0)
    elif a.cmd == "kalshi-link":
        from .jobs import link_kalshi
        print(link_kalshi(a.demo_id, a.ticker, a.yes, a.start))
    elif a.cmd == "kalshi-all":
        from . import report
        df = report.kalshi_all(relink=a.relink)
        if len(df):
            print(df.drop(columns=["demo"]).to_string(index=False))
            print(report.summarize(df))
    elif a.cmd == "kalshi-realign":
        import collections

        from . import kalshi
        counts = collections.Counter()
        for d in [r["id"] for r in db.rows("SELECT id FROM demos WHERE kalshi_status='linked'")]:
            try:
                before = kalshi.link_info(d)["start_ts"]
                after = kalshi.realign(d)["start_ts"]
                conf = kalshi.alignment_quality(d).get("confidence")
            except Exception as e:  # keep going: one bad tape must not stop the batch
                conf, before, after = f"error: {e}", 0, 0
            db.update_demo(d, kalshi_confidence=conf)
            counts[conf] += 1
            print(f"{conf:6s} shift {after - before:+5d}s  {d}")
        print(dict(counts))
    elif a.cmd == "sites":
        import json

        from . import sites
        print(json.dumps(sites.rebuild(), indent=1, sort_keys=True))
    elif a.cmd == "remove":
        from .jobs import remove_demo
        for d in a.ids:
            remove_demo(d)
            print(f"removed {d}")
    elif a.cmd == "publish-all":
        from cs2wp_core import storage
        s = storage.store()
        if s.kind == "local":
            print("CS2WP_STORAGE=local: nothing to publish")
        else:
            s.ensure_buckets()
            prefixes = ["parsed", "features", "scores", "kalshi", "models", "catalog"]
            n = sum(s.publish_tree(p) for p in prefixes + ([] if a.skip_raw else ["raw"]))
            print(f"published {n} files")
    elif a.cmd == "catalog-export":
        print(f"exported {db.export_catalog()} demos")
    elif a.cmd == "catalog-import":
        print(f"imported {db.import_catalog()} demos")
    elif a.cmd == "status":
        for r in db.rows("SELECT status, COUNT(*) AS n FROM demos GROUP BY status"):
            print(r)
