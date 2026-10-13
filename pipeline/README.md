# pipeline (`cs2wp-pipeline`)

```
HLTV downloader / manual drop → uploads/ (or data/inbox) → watcher → ingest → parse → features
→ score (round P, map P) → Kalshi link
```

| Command | What |
|---|---|
| `worker` | Run queued jobs; watch `data/inbox` and storage `uploads/` |
| `runtime` | Live runtime (Kafka): replay runs started by the API |
| `hltv-discover` / `hltv-download` / `hltv-sync` / `hltv-status` | Record starred HLTV matches since CS2, download them into `uploads/`, both on repeat, progress |
| `ingest <files>` / `process <ids>` | Do the work now, in this process |
| `enqueue <kind> [id]` | Queue a job |
| `rescore` | Re-score every map (held-out model per match) |
| `features` | Rebuild features from the stored parse |
| `validate-live <ids> [--rounds N]` | Check the live path matches batch at every tick |
| `kalshi-link <id> [--ticker T --yes a\|b]` / `kalshi-all [--relink]` / `kalshi-realign` | Link one match / all maps / refit alignment offline |
| `remove <ids>` | Delete maps and everything derived |
| `publish-all [--skip-raw]`, `catalog-export`, `catalog-import` | Copy local data to S3; move the catalog between databases |
| `sites` | Relearn bomb-site centres |

Notes:
- HLTV blocks plain HTTP clients, so the downloader uses `curl_cffi` impersonating Chrome, one download
  at a time with `CS2WP_HLTV_DELAY` seconds between requests (default 4).
- HLTV archives use the newest RAR format: extraction tries RARLAB `unrar`, then `unar`, then `7zz`.
- A parse peaks at ~2.3 GB, so a worker parses one map at a time (`CS2WP_PARSE_CONCURRENCY`).
- Kalshi markets older than ~2 months are on its `/historical` endpoints; both are checked.

Tests: `uv run pytest` in `pipeline/`; `CS2WP_TEST_DEMO=/path/to.dem` adds end-to-end tests.
