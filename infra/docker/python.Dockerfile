# syntax=docker/dockerfile:1
# One image for every Python service (api, pipeline worker, live runtime, ml worker).
# Build context = repo root:  docker build -f infra/docker/python.Dockerfile .
FROM python:3.12-slim-trixie

# HLTV archives use the newest RAR format. RARLAB's unrar (Debian non-free) is the only Linux
# extractor that unpacks all of them: Debian's unar 1.10.1/1.10.8 fails part-way through some maps
# and 7-Zip can't open them. unar and 7zz stay as fallbacks.
RUN sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends unrar unar 7zip libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /bin/uv

WORKDIR /src
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
COPY core core
COPY pipeline pipeline
COPY ml ml
COPY api api
# cs2wp-api depends on pipeline, ml and core, so this installs every service's entry point.
# uv's download cache lives in a build cache mount, not in the image (~1 GB smaller).
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package cs2wp-api
ENV PATH=/opt/venv/bin:$PATH CS2WP_DATA=/data
RUN useradd -m -u 1000 app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
CMD ["cs2wp-api", "--host", "0.0.0.0", "--port", "8000"]
