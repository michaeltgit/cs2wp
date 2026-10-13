# web

Vue 3 + TypeScript + Vite + Pinia website. Talks only to the API (HTTP + one WebSocket).

- Demo view: radar replay, round strip, kill feed with win-probability swings, P(CT) chart, player impact.
- Playback: stored replay (−4× to 8×) or live mode through the server's live path.
- Map win probability vs Kalshi: whole map, trade by trade per round, and an analysis card.
- Sidebar: demos, jobs, models (switch the active one), data status. Deep links: `#demo=<id>&round=<n>`.
- Keys: `Space` play/pause · `←/→` ±5 s · `Shift+←/→` round · `,` `.` ±1 tick.

```bash
npm ci
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
npm test           # also: npm run lint, npm run build
```

`API_PROXY_TARGET` changes the dev proxy target. `VITE_API_BASE` sets the API origin at build time;
leave it empty when the site and API share an origin (CloudFront on AWS, nginx in Docker).
Code: `src/api` (client + types), `src/stores`, `src/components`, `src/lib/draw` (canvas drawing).
