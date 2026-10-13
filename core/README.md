# core (`cs2wp-core`)

Shared library imported by every Python service, so contracts, storage keys, features and the map
model never drift between training, batch scoring, live inference and the API.

| Module | What |
|---|---|
| `config` | Settings from `CS2WP_*` environment variables |
| `contracts` | Message schemas and Kafka topic names |
| `storage` | Local folder or S3, same keys |
| `db` | SQLite or Postgres: `demos`, `jobs` (durable queue), `downloads` |
| `bus` | In-process or Kafka |
| `features` | Per-tick model inputs (identical live and batch) |
| `mapwin` | Map win probability from round probability + score (MR12 / overtime rules) |
| `modeling` | Model registry and loading; picks the held-out model for a match |

| Variable | Default | Docker / AWS |
|---|---|---|
| `CS2WP_DATA` | `<repo>/data` | local data dir / cache |
| `CS2WP_STORAGE` | `local` | `s3` |
| `CS2WP_S3_ENDPOINT` | AWS | `http://localhost:9000` locally |
| `CS2WP_S3_BUCKET_DEMOS` / `_GS` / `_MODELS` | `cs2wp-demo-archive` / `cs2wp-gs-data` / `cs2wp-model-artifacts` | bucket names |
| `CS2WP_DATABASE_URL` | SQLite in `CS2WP_DATA` | `postgresql+psycopg://…` |
| `CS2WP_DATABASE_PASSWORD` | unset | fills `{password}` in the URL |
| `CS2WP_BUS` / `CS2WP_KAFKA_BOOTSTRAP` | `inprocess` / `localhost:19092` | `kafka` |

Tests: `uv run pytest` in `core/`.
