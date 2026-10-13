"""Settings shared by every service, read from environment variables (12-factor).

Local "lite" mode needs no configuration: data in <repo root>/data, SQLite, local-folder storage and an
in-process message bus. Point the same variables at S3 (SeaweedFS locally), Postgres and Kafka for the stack.

    CS2WP_DATA            local working directory / cache        (default: <repo root>/data)
    CS2WP_STORAGE         local | s3                              (default: local)
    CS2WP_S3_ENDPOINT     e.g. http://localhost:9000 locally      (default: AWS)
    CS2WP_S3_BUCKET_DEMOS / _GS / _MODELS                         (default: cs2wp-demo-archive / cs2wp-gs-data / cs2wp-model-artifacts)
    CS2WP_DATABASE_URL    sqlite:///... | postgresql+psycopg://... (default: sqlite in CS2WP_DATA)
    CS2WP_DATABASE_PASSWORD  fills a literal {password} in the URL, URL-encoded (AWS: from Secrets Manager)
    CS2WP_BUS             inprocess | kafka                       (default: inprocess)
    CS2WP_KAFKA_BOOTSTRAP e.g. localhost:19092                    (default: localhost:19092)
"""

import os
from pathlib import Path
from urllib.parse import quote


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _default_data() -> Path:
    """<repo root>/data when run from anywhere inside the monorepo (root = the uv workspace), else ./data."""
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        pp = d / "pyproject.toml"
        if pp.is_file() and "[tool.uv.workspace]" in pp.read_text():
            return d / "data"
    return here / "data"


DATA = Path(_env("CS2WP_DATA", str(_default_data()))).expanduser().resolve()

INBOX = DATA / "inbox"          # browser downloads land here; the watcher ingests + cleans up
UPLOADS = DATA / "uploads"      # staged archives (backend ingest)
RAW = DATA / "raw"
PARSED = DATA / "parsed"
FEATURES = DATA / "features"
SCORES = DATA / "scores"
MODELS = DATA / "models"
KALSHI = DATA / "kalshi"
CACHE = DATA / "cache"          # derived, never uploaded (e.g. map backgrounds)

STORAGE = _env("CS2WP_STORAGE", "local")
S3_ENDPOINT = os.environ.get("CS2WP_S3_ENDPOINT") or None
S3_BUCKETS = {
    "demos": _env("CS2WP_S3_BUCKET_DEMOS", "cs2wp-demo-archive"),
    "gs": _env("CS2WP_S3_BUCKET_GS", "cs2wp-gs-data"),
    "models": _env("CS2WP_S3_BUCKET_MODELS", "cs2wp-model-artifacts"),
}
CACHE_TTL = float(_env("CS2WP_CACHE_TTL", "15"))  # seconds before a cached S3 object is revalidated
DATABASE_URL = _env("CS2WP_DATABASE_URL", f"sqlite:///{DATA / 'app.db'}")
if "{password}" in DATABASE_URL:  # RDS keeps the password in Secrets Manager; it arrives separately
    DATABASE_URL = DATABASE_URL.replace("{password}", quote(os.environ.get("CS2WP_DATABASE_PASSWORD", ""), safe=""))
BUS = _env("CS2WP_BUS", "inprocess")
KAFKA_BOOTSTRAP = _env("CS2WP_KAFKA_BOOTSTRAP", "localhost:19092")

# ---- game constants ----
TICKRATE = 64           # CS2 server ticks per second; every tick has all 10 players
PARSE_EVERY = 1         # store every tick (64 Hz) for replay + scoring
TRAIN_EVERY = 8         # training subsample (8 Hz); neighbouring ticks are near duplicates
POST_ROUND_TICKS = 3 * TICKRATE  # keep 3 s after round_end in the replay
ROUND_TIME = 115.0      # mp_roundtime 1:55
BOMB_TIME = 40.0        # mp_c4timer
CT, T = 3, 2
# round_end.reason values kept as labels: bombed, defused, CT elim, T elim, time ran out
VALID_REASONS = {1, 7, 8, 9, 12}


def ensure_dirs():
    for d in (INBOX, UPLOADS, RAW, PARSED, FEATURES, SCORES, MODELS, KALSHI, CACHE):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()
