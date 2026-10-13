import { parseJSON } from '@/lib/json';
import type {
  ActivateResponse,
  DemoDetail,
  DemoSummary,
  Job,
  KalshiAnalysis,
  KalshiComparison,
  KalshiRoundTrades,
  MapInfo,
  MapWinSeries,
  ModelRegistry,
  RoundData,
  StatusResponse,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Normalise a configured base URL: trims whitespace and trailing slashes ('' = same origin). */
export function normalizeBase(base: string | null | undefined): string {
  return (base ?? '').trim().replace(/\/+$/, '');
}

/** base + path, where path starts with '/'. */
export function joinUrl(base: string, path: string): string {
  const b = normalizeBase(base);
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${b}${p}`;
}

interface LocationLike {
  protocol: string;
  host: string;
}

/**
 * WebSocket URL for a path. With an absolute API base its scheme is swapped (http->ws,
 * https->wss); with an empty or relative base the page location is used.
 */
export function wsUrl(base: string, path: string, loc: LocationLike): string {
  const b = normalizeBase(base);
  const p = path.startsWith('/') ? path : `/${path}`;
  const m = /^(https?):\/\/(.+)$/i.exec(b);
  if (m) return `${m[1]!.toLowerCase() === 'https' ? 'wss' : 'ws'}://${m[2]}${p}`;
  const proto = loc.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${loc.host}${b}${p}`;
}

/** Build a query string, skipping null/undefined values. */
export function query(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : '';
}

const enc = encodeURIComponent;

async function errorText(r: Response): Promise<string> {
  try {
    const j = parseJSON<{ detail?: unknown }>(await r.text());
    return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
  } catch {
    return `${r.status} ${r.statusText}`.trim();
  }
}

export interface ApiClientOptions {
  base?: string;
  fetch?: typeof fetch;
  location?: LocationLike;
}

export type ApiClient = ReturnType<typeof createApiClient>;

export function createApiClient(opts: ApiClientOptions = {}) {
  const base = normalizeBase(opts.base);
  const doFetch: typeof fetch = opts.fetch ?? ((...a) => fetch(...a));
  const loc = (): LocationLike => opts.location ?? window.location;
  const url = (path: string) => joinUrl(base, path);

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await doFetch(url(path), init);
    if (!r.ok) throw new ApiError(await errorText(r), r.status);
    return parseJSON<T>(await r.text());
  }
  const get = <T>(path: string) => request<T>(path, { cache: 'no-store' });
  const post = <T>(path: string) => request<T>(path, { method: 'POST' });

  return {
    base,
    url,
    get,
    post,
    wsUrl: (path: string) => wsUrl(base, path, loc()),

    demos: () => get<DemoSummary[]>('/api/demos'),
    jobs: () => get<Job[]>('/api/jobs'),
    job: (id: string) => get<Job>(`/api/jobs/${enc(id)}`),
    demo: (id: string) => get<DemoDetail>(`/api/demos/${enc(id)}`),
    round: (id: string, n: number) => get<RoundData>(`/api/demos/${enc(id)}/rounds/${n}`),
    map: (name: string) => get<MapInfo>(`/api/maps/${enc(name)}`),
    models: () => get<ModelRegistry>('/api/models'),
    activateModel: (v: string) => post<ActivateResponse>(`/api/models/${enc(v)}/activate`),
    calibrationUrl: (v: string, bust?: string | number | null) =>
      url(`/api/models/${enc(v)}/calibration.png${query({ t: bust ?? '' })}`),
    status: () => get<StatusResponse>('/api/status'),

    kalshi: (id: string) => get<KalshiComparison>(`/api/demos/${enc(id)}/kalshi`),
    kalshiAnalysis: (id: string) => get<KalshiAnalysis>(`/api/demos/${enc(id)}/kalshi/analysis`),
    kalshiRound: (id: string, n: number) => get<KalshiRoundTrades>(`/api/demos/${enc(id)}/kalshi/rounds/${n}`),
    mapwin: (id: string, opts: { every?: number; round?: number } = {}) =>
      get<MapWinSeries>(`/api/demos/${enc(id)}/mapwin${query({ every: opts.every, round: opts.round })}`),

    liveUrl: (id: string, n: number) => wsUrl(base, `/ws/live/${enc(id)}/${n}`, loc()),
  };
}

/** The app-wide client, configured from VITE_API_BASE. */
export const api = createApiClient({ base: import.meta.env.VITE_API_BASE ?? '' });
