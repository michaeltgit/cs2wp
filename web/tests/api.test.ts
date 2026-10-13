import { describe, expect, it, vi } from 'vitest';
import { ApiError, createApiClient, joinUrl, normalizeBase, query, wsUrl } from '@/api/client';

const page = { protocol: 'http:', host: 'localhost:5173' };
const securePage = { protocol: 'https:', host: 'app.example.com' };

function fakeFetch(body: string, init: { status?: number; statusText?: string } = {}) {
  return vi.fn(async (_url: string | URL | Request, _opts?: RequestInit) =>
    new Response(body, { status: init.status ?? 200, statusText: init.statusText ?? 'OK' }),
  );
}

describe('URL building', () => {
  it('normalizes the base', () => {
    expect(normalizeBase(undefined)).toBe('');
    expect(normalizeBase('  https://api.example.com//  ')).toBe('https://api.example.com');
  });

  it('joins base and path', () => {
    expect(joinUrl('', '/api/demos')).toBe('/api/demos');
    expect(joinUrl('https://api.example.com/', '/api/demos')).toBe('https://api.example.com/api/demos');
    expect(joinUrl('https://api.example.com/prefix', 'api/x')).toBe('https://api.example.com/prefix/api/x');
  });

  it('derives the WebSocket URL from the API base', () => {
    expect(wsUrl('', '/ws/live/a/1', page)).toBe('ws://localhost:5173/ws/live/a/1');
    expect(wsUrl('', '/ws/live/a/1', securePage)).toBe('wss://app.example.com/ws/live/a/1');
    expect(wsUrl('http://127.0.0.1:8000', '/ws/x', securePage)).toBe('ws://127.0.0.1:8000/ws/x');
    expect(wsUrl('https://api.example.com/', '/ws/x', page)).toBe('wss://api.example.com/ws/x');
    expect(wsUrl('/backend', '/ws/x', page)).toBe('ws://localhost:5173/backend/ws/x');
  });

  it('builds query strings, skipping nullish values', () => {
    expect(query({ q: 'Vitality fe', days: 60 })).toBe('?q=Vitality+fe&days=60');
    expect(query({ every: undefined, round: null })).toBe('');
    expect(query({ every: 1, round: 3 })).toBe('?every=1&round=3');
  });
});

describe('endpoints', () => {
  it('encodes ids and builds every endpoint against the base', async () => {
    const fetch = fakeFetch('{}');
    const api = createApiClient({ base: 'https://api.example.com', fetch, location: page });
    const id = 'a b/c';
    await api.demos();
    await api.demo(id);
    await api.round(id, 4);
    await api.map('de_mirage');
    await api.mapwin(id);
    await api.mapwin(id, { every: 1, round: 7 });
    await api.kalshi(id);
    await api.kalshiAnalysis(id);
    await api.kalshiRound(id, 2);
    await api.status();
    await api.jobs();
    await api.job('j1');
    await api.models();
    const urls = fetch.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual([
      'https://api.example.com/api/demos',
      'https://api.example.com/api/demos/a%20b%2Fc',
      'https://api.example.com/api/demos/a%20b%2Fc/rounds/4',
      'https://api.example.com/api/maps/de_mirage',
      'https://api.example.com/api/demos/a%20b%2Fc/mapwin',
      'https://api.example.com/api/demos/a%20b%2Fc/mapwin?every=1&round=7',
      'https://api.example.com/api/demos/a%20b%2Fc/kalshi',
      'https://api.example.com/api/demos/a%20b%2Fc/kalshi/analysis',
      'https://api.example.com/api/demos/a%20b%2Fc/kalshi/rounds/2',
      'https://api.example.com/api/status',
      'https://api.example.com/api/jobs',
      'https://api.example.com/api/jobs/j1',
      'https://api.example.com/api/models',
    ]);
    // GETs bypass the HTTP cache like the original UI
    expect(fetch.mock.calls[0]![1]).toMatchObject({ cache: 'no-store' });
    expect(api.liveUrl(id, 3)).toBe('wss://api.example.com/ws/live/a%20b%2Fc/3');
    expect(api.calibrationUrl('v008', 1791841089.2)).toBe('https://api.example.com/api/models/v008/calibration.png?t=1791841089.2');
  });

  it('same-origin by default', async () => {
    const fetch = fakeFetch('[]');
    const api = createApiClient({ fetch, location: page });
    await api.demos();
    expect(String(fetch.mock.calls[0]![0])).toBe('/api/demos');
    expect(api.liveUrl('x', 1)).toBe('ws://localhost:5173/ws/live/x/1');
  });

  it('the only write is switching the active model', async () => {
    const fetch = fakeFetch('{"job_id":"j"}');
    const api = createApiClient({ fetch, location: page });
    await api.activateModel('v1');
    expect(fetch.mock.calls.map((c) => [String(c[0]), c[1]?.method])).toEqual([['/api/models/v1/activate', 'POST']]);
  });

  it('tolerates bare NaN in responses', async () => {
    const api = createApiClient({ fetch: fakeFetch('{"tick":[1,2],"price_a":[NaN,0.5]}'), location: page });
    expect(await api.get('/api/x')).toEqual({ tick: [1, 2], price_a: [null, 0.5] });
  });

  it('surfaces FastAPI error details', async () => {
    const api = createApiClient({ fetch: fakeFetch('{"detail":"no Kalshi market linked"}', { status: 404 }), location: page });
    await expect(api.kalshi('d')).rejects.toMatchObject({ message: 'no Kalshi market linked', status: 404 });
    await expect(api.kalshi('d')).rejects.toBeInstanceOf(ApiError);
  });

  it('falls back to the status line for non-JSON errors', async () => {
    const api = createApiClient({ fetch: fakeFetch('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }), location: page });
    await expect(api.demos()).rejects.toThrow('502 Bad Gateway');
  });

  it('stringifies structured error details', async () => {
    const api = createApiClient({ fetch: fakeFetch('{"detail":[{"msg":"field required"}]}', { status: 422 }), location: page });
    await expect(api.activateModel('v1')).rejects.toThrow('[{"msg":"field required"}]');
  });
});

