"""Object storage behind one interface: a local folder or S3 (AWS, or SeaweedFS locally).

Every artifact has a *key* that is also its path relative to CS2WP_DATA, e.g.
``parsed/<demo_id>/ticks.parquet``. Workers write files locally (the Linux processing cache) and
``publish`` them; readers call ``local_path`` which returns a local file, downloading it from S3
first when needed. With the local backend the cache *is* the store, so both are no-ops.

Bucket routing (S3): ``raw/`` + ``uploads/`` -> demo archive, ``models/`` -> model artifacts, everything else
-> gs-data (parsed states, features, scores, kalshi, catalog).
"""

from __future__ import annotations

import re
import time
from functools import lru_cache
from pathlib import Path

from . import config


def key_of(path: Path | str) -> str:
    p = Path(path).resolve()
    return p.relative_to(config.DATA).as_posix()


class LocalStore:
    kind = "local"

    def local_path(self, key: str, fetch: bool = True) -> Path:
        return config.DATA / key

    def exists(self, key: str) -> bool:
        return (config.DATA / key).exists()

    def publish(self, key: str) -> None:  # file already lives in the store
        return None

    def publish_tree(self, prefix: str) -> int:
        return 0

    def list(self, prefix: str) -> list[str]:
        base = config.DATA / prefix
        if base.is_file():
            return [prefix]
        if not base.exists():
            return []
        return sorted(key_of(p) for p in base.rglob("*")
                      if p.is_file() and not p.name.endswith((".etag", ".part")) and p.name != ".DS_Store")

    def delete(self, key: str) -> None:
        (config.DATA / key).unlink(missing_ok=True)


class S3Store:
    kind = "s3"

    def __init__(self):
        import boto3
        self.s3 = boto3.client("s3", endpoint_url=config.S3_ENDPOINT)
        self._seen: dict[str, tuple[str | None, float]] = {}

    @staticmethod
    def bucket_for(key: str) -> str:
        top = key.split("/", 1)[0]
        return config.S3_BUCKETS["demos" if top in ("raw", "uploads") else "models" if top == "models" else "gs"]

    # keys that never change once written: cached copies never need revalidating
    IMMUTABLE = re.compile(r"^(raw/|uploads/|models/v\d+/)")

    def _fresh(self, key: str, p: Path) -> bool:
        """A cached copy is reused for CACHE_TTL seconds, then revalidated by ETag (another service
        may have rewritten it: rescoring, relinking Kalshi, a new registry)."""
        if not p.exists():
            return False
        if self.IMMUTABLE.match(key):
            return True
        etag, checked = self._seen.get(key, (None, 0.0))
        if time.time() - checked < config.CACHE_TTL:
            return True
        try:
            remote = self.s3.head_object(Bucket=self.bucket_for(key), Key=key)["ETag"]
        except Exception:
            return True  # deleted remotely or unreachable: keep serving the cached copy
        if etag is None:  # first sight in this process: trust the file only if it matches
            etag = self._etags_file(p).read_text() if self._etags_file(p).exists() else None
        if remote == etag:
            self._seen[key] = (etag, time.time())
            return True
        return False

    @staticmethod
    def _etags_file(p: Path) -> Path:
        return p.with_name(p.name + ".etag")

    def _remember(self, key: str, p: Path, etag: str | None) -> None:
        if etag:
            self._etags_file(p).write_text(etag)
            self._seen[key] = (etag, time.time())

    def local_path(self, key: str, fetch: bool = True) -> Path:
        p = config.DATA / key
        if fetch and not self._fresh(key, p):
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".part")
            try:
                bucket = self.bucket_for(key)
                etag = self.s3.head_object(Bucket=bucket, Key=key)["ETag"]
                self.s3.download_file(bucket, key, str(tmp))
                tmp.replace(p)
                self._remember(key, p, etag)
            except Exception:
                tmp.unlink(missing_ok=True)
        return p

    def exists(self, key: str) -> bool:
        if (config.DATA / key).exists():
            return True
        try:
            self.s3.head_object(Bucket=self.bucket_for(key), Key=key)
            return True
        except Exception:
            return False

    def publish(self, key: str) -> None:
        p = config.DATA / key
        if p.exists():
            bucket = self.bucket_for(key)
            self.s3.upload_file(str(p), bucket, key)
            if not self.IMMUTABLE.match(key):
                self._remember(key, p, self.s3.head_object(Bucket=bucket, Key=key)["ETag"])

    def publish_tree(self, prefix: str) -> int:
        n = 0
        for key in LocalStore().list(prefix):
            self.publish(key)
            n += 1
        return n

    def list(self, prefix: str) -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket_for(prefix), "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            out += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return sorted(out)
            token = r["NextContinuationToken"]

    def delete(self, key: str) -> None:
        (config.DATA / key).unlink(missing_ok=True)
        try:
            self.s3.delete_object(Bucket=self.bucket_for(key), Key=key)
        except Exception:
            pass

    def ensure_buckets(self) -> None:
        for b in set(config.S3_BUCKETS.values()):
            try:
                self.s3.head_bucket(Bucket=b)
            except Exception:
                self.s3.create_bucket(Bucket=b)


@lru_cache(maxsize=1)
def store():
    return S3Store() if config.STORAGE == "s3" else LocalStore()


def local_path(key: str, fetch: bool = True) -> Path:
    """Local file for a key (downloaded from object storage if needed)."""
    return store().local_path(key, fetch)


def publish(*keys_or_paths) -> None:
    """Upload freshly written local files to object storage (no-op for the local backend)."""
    s = store()
    for k in keys_or_paths:
        s.publish(k if isinstance(k, str) else key_of(k))


def exists(key: str) -> bool:
    return store().exists(key)
