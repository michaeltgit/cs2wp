# cs2wp

CS2 round and map win probability from pro match demos, compared against Kalshi prediction markets:
does our model price CS2 maps better than the market?

**Status: working prototype.** The historical path runs end to end locally and in an AWS-shaped
Docker setup. Live data (GRID), the AWS deploy and model work are planned
[expansion points](docs/DEPLOYMENT.md#expansion-points).

## How it works

1. **Demos in:** the HLTV downloader (or a manual drop) puts archives in storage `uploads/`; a watcher queues ingest.
2. **Pipeline:** unpack → parse every tick → 68 game-state features → P(CT wins the round) per tick and map
   win probability → link the match to its Kalshi markets.
3. **Model:** LightGBM on game state only, evaluated by match; every map is scored by a model that never saw it.
4. **Website (view-only):** replays, win probability, our map odds next to Kalshi, models, data status.
   Data changes are backend commands.
5. **Live later:** replays already use the live path (Kafka → live inference → WebSocket); GRID would plug in there.

Storage, database and message bus each have a local and an AWS-shaped backend; the code is the same.

Docs: [architecture](docs/ARCHITECTURE.md) · [deployment + expansion points](docs/DEPLOYMENT.md) ·
[diagram](docs/architecture.excalidraw) (open at excalidraw.com)

## Layout

| Folder | What |
|---|---|
| [`core/`](core) | Shared library: contracts, storage, DB, bus, features, map odds, model loading |
| [`pipeline/`](pipeline) | HLTV downloader, ingest, parse, score, Kalshi, job worker, live runtime |
| [`ml/`](ml) | Training, evaluation, model registry |
| [`api/`](api) | FastAPI: read endpoints, model switching, live WebSocket |
| [`web/`](web) | Vue 3 website, with its Dockerfile and nginx config |
| [`infra/`](infra) | Dockerfile for the Python services, Terraform for AWS (not applied) |
| [`scripts/`](scripts) | Sample data: `seed.py`, `make_seed.py` |
| [`docs/`](docs) | Architecture, deployment, the diagram |

Python packages use the standard src layout (`core/src/cs2wp_core/`, tests in `core/tests/`) and share one
uv workspace (root `pyproject.toml`, one `uv.lock`). `data/` holds local data and is not in git.

## Run it

### Docker mode (the full system, as it would run on AWS)

Needs [Docker](https://docs.docker.com/get-docker/) with at least 8 GB of memory for it, and
[uv](https://docs.astral.sh/uv/) (loads the sample data). On a Mac without Docker Desktop:
`brew install colima docker docker-compose docker-buildx && colima start --cpu 4 --memory 8`.

```bash
git clone https://github.com/michaeltgit/cs2wp && cd cs2wp && uv sync --all-packages
docker compose up -d                          # stand-ins: S3 (SeaweedFS), Postgres, Kafka (Redpanda)
python3 scripts/seed.py --stack               # sample data: 3 matches, 8 maps, the current model
docker compose --profile app up -d --build    # our services
```

Open http://localhost:8080. Stop with `docker compose --profile app down` (data is kept in Docker
volumes; add `-v` to delete it). If Docker runs out of disk: `docker builder prune -af`.

### Lite mode (no Docker; for development)

A local folder instead of S3, SQLite instead of Postgres, an in-process queue instead of Kafka. Needs
uv and Node 20+ (on a Mac, `brew install unar` to unpack HLTV archives).

```bash
python3 scripts/seed.py                 # sample data into ./data
uv run cs2wp-api                        # API + workers on :8000
(cd web && npm ci && npm run dev)       # http://localhost:5173
```

## Commands

From the repo root. In Docker mode replace `uv run` with `docker compose exec pipeline-worker` (`ml-worker` for `cs2wp-ml`).

| Task | Command |
|---|---|
| Download from HLTV | `uv run cs2wp-pipeline hltv-sync --pages 1 --limit 10` · `hltv-status` · continuous: `docker compose --profile downloader up -d` |
| Add a demo by hand | put it in `data/inbox` or storage `uploads/`, or `uv run cs2wp-pipeline ingest <files>` |
| Re-process / delete a map | `uv run cs2wp-pipeline process <demo_id>` / `remove <demo_id>` |
| Rebuild features | `uv run cs2wp-pipeline features` |
| Check live == batch | `uv run cs2wp-pipeline validate-live <demo_id> --rounds 3` |
| Train and use a model | `uv run cs2wp-ml train --activate` |
| Switch model | website, or `uv run cs2wp-ml activate <version>` |
| Kalshi link / re-link all | `uv run cs2wp-pipeline kalshi-link <demo_id>` / `kalshi-all --relink` |
| Status | `uv run cs2wp-pipeline status` |

The downloader takes HLTV starred matches since CS2's release, newest first, one at a time, skipping
ones we have. Check HLTV's terms before large runs.

## Sample data, tests, CI

- Sample data is the GitHub release `seed-v3`. New version: `scripts/make_seed.py --tag vN`, `gh release create seed-vN dist/*`, bump the default tag in `scripts/seed.py`.
- Tests: `uv run ruff check .`; `uv run pytest` in `core/`, `pipeline/`, `ml/`, `api/`; `npm test` in `web/`. `CS2WP_TEST_DEMO=/path/to.dem` adds end-to-end demo tests.
- CI (`.github/workflows/`): `python.yml` (lint, tests, image `ghcr.io/michaeltgit/cs2wp` on `main`), `web.yml`, `infra.yml`; each runs only when its folders change.
