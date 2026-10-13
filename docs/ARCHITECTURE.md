# Architecture

Working prototype: what is built, why, and how it maps to the team's original reference design
(three AWS diagrams: full architecture, runtime controls, deployment).
Diagram: [`architecture.excalidraw`](architecture.excalidraw): neutral = built, purple dashed = live / GRID
expansion, red dashed = other expansion, orange "→ AWS" = local stand-in for an AWS service, dashed grey
arrows = reads / loads.

## Principles

| Principle | Why |
|---|---|
| Model fair value shown **next to** the Kalshi price, never blended | The point is to test whether the model beats the market |
| Every map scored **out-of-sample** | In-sample numbers fake an edge |
| Round model sees **game state only** (no score, round number, team) | Those let it memorise matches; held-out results got worse with them |
| **One feature library** for training, batch and live | Train/serve skew ruins models; `validate-live` checks it |
| **Same code everywhere**, backends chosen by settings | Local tests mean something on AWS |
| **Parse once**, keep originals and everything derived in storage | Downloads are the bottleneck |
| **View-only website**; data changes are backend commands | Nothing on the site needs protecting |
| **Few services, one repo** | One team, fewer moving parts |

## Components

**A. Offline pipeline + model**
- `pipeline/acquire.py`: HLTV starred results since CS2 → `downloads` table → archive into `uploads/`.
- Watchers (`jobs.py`): new files in `uploads/` or `data/inbox` → `ingest` job.
- `ingest.py`: unpack (unrar → unar → 7zz), one map per `.dem`, dedupe (sha1 + match fingerprint).
- `parse.py`: demoparser2 in a child process, one at a time (~2.3 GB per map).
- `core/features.py`: 68 inputs per tick from data up to that tick.
- `score.py`, `core/mapwin.py`: round P per tick; map P from round P, score, CT round rate, MR12/OT rules.
- `kalshi.py`: markets, candles, trades (regular + archived); whole match → one Kalshi match whose
  settled results agree; clocks aligned from the trade tape.
- `ml/`: LightGBM + isotonic, regulation rounds at 8/s, grouped by match; one held-out model per match.

**B. Shared runtime** (`pipeline/runtime.py`): replay streamer → `raw-gs` → live inference →
`round-predictions` → API WebSocket. One runtime process consumes `system-commands`. GRID would publish
the same `RawGSFrame`.

**C. Delivery**: FastAPI (reads, `POST /api/models/{v}/activate`, `WS /ws/live/{demo}/{round}`) and the
Vue site; nginx locally, S3 + CloudFront on AWS (same origin).

**D. Control plane + storage**: Postgres (SQLite in lite) for `demos`, `jobs` (`SKIP LOCKED` queue) and
`downloads`; storage for every file; Kafka for live runs only.

## Data

| Storage key | Contents |
|---|---|
| `uploads/`, `raw/<demo_id>.dem` | incoming archives, original demos |
| `parsed/<demo_id>/`, `features/`, `scores/`, `kalshi/`, `catalog/` | game state, inputs, outputs, market data, catalog snapshot |
| `models/<version>/`, `models/registry.json` | models, held-out models, active version |

Kafka topics (keyed by run_id, contracts in `core/contracts.py`): `raw-gs`, `round-predictions`,
`system-commands`, `system-events`; `market-quotes`, `map-evidence`, `ui-game-state` for unbuilt live pieces.

## Versus the reference design

- **Kept:** one game-state message for replay and GRID; shared inference per run; game-state-only round
  model; parse once; durable Postgres jobs; self-hosted Kafka; no Lambda for live work; the four S3
  buckets; a real map model; the validation gate.
- **Simplified:** fewer services (one live process, one API); jobs go Postgres → workers directly; no
  checkpoints for replays; Linux host is EC2 in stage 1 (no VPN).
- **Left out:** viewer personalization (priors, viewer projector, series fair values). We compare our
  model with the market; a viewer's opinion is either something to learn in training or noise.
- **Added:** Kalshi data and the comparison, out-of-sample scoring, local stand-ins, sample data.
- **Not built:** see [expansion points](DEPLOYMENT.md#expansion-points).

## Findings

1. Prototype held-out models were calibrated on their own training predictions (0.625 log loss vs 0.46). Fixed.
2. Kalshi alignment used our model's odds; now score changes only. 18 of 71 maps moved > 90 s.
3. `equip_diff` wrapped to ~4.3e9 when T had more equipment (uint32); models up to v010 trained on it.
4. Four maps were linked to the wrong Kalshi match (old links, "G2" inside "Aug 28", a second meeting).
5. Bomb-site centres existed for 3 of 8 maps; `in_bomb_zone` only marks the bomb carrier.
6. Linux `unar` fails on some HLTV archives; the image uses RARLAB `unrar`.
7. Parsing two maps at once ran out of memory; now one at a time.
8. HLTV team ratings were a shortcut and were removed; team strength belongs in training.
