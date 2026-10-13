# api (`cs2wp-api`)

FastAPI service for the website. Read-only apart from switching the active model.

```bash
uv run cs2wp-api        # :8000; in lite mode the workers run inside it
```

Endpoints: `GET /healthz`, `/api/demos`, `/api/demos/{id}`, `/api/demos/{id}/rounds/{n}`,
`/api/demos/{id}/mapwin`, `/api/demos/{id}/kalshi[/analysis|/rounds/{n}]`, `/api/maps/{map}`,
`/api/models`, `/api/models/{v}/calibration.png`, `/api/jobs[/{id}]`, `/api/status`;
`POST /api/models/{v}/activate`; `WS /ws/live/{id}/{round}`. OpenAPI at `/docs`.

Live replay: in lite mode the run happens in this process; with Kafka the API sends commands on
`system-commands`, waits for the runtime's `RUNNING` event and forwards `round-predictions`.

Settings: `CS2WP_EMBEDDED_WORKERS` (default on with SQLite), `CS2WP_CORS_ORIGINS` (only needed when
the site is on another origin, e.g. the Vite dev server), `CS2WP_WEB_DIST` (serve a built site at `/app/`).
