export const TICKRATE = 64;
export const CT = 3;
export const T = 2;
export type Side = typeof CT | typeof T;

export const COLOR = {
  ct: '#5b9bd5',
  t: '#e8a33d',
  bomb: '#ff4b3e',
  text: '#d8dde6',
  muted: '#8a93a3',
  faint: '#5d6575',
  grid: '#262d38',
} as const;

/** Map chart colours: our model vs the Kalshi market. */
export const MAPC = { ours: '#51cf66', kal: '#b197fc' } as const;

export const ROUND_TIME = 115; // 1:55
export const BOMB_TIME = 40;
export const SPEEDS = [-4, -2, -1, 0.25, 0.5, 1, 2, 4, 8] as const;
export const FEED_TYPES = new Set(['kill', 'plant', 'defuse_start', 'defuse', 'explode']);

export type NadeType = 'smoke' | 'molotov' | 'flash' | 'he';
export const NADES: Record<NadeType, { dur: number; r: number }> = {
  smoke: { dur: 18, r: 144 },
  molotov: { dur: 7, r: 120 },
  flash: { dur: 0.5, r: 90 },
  he: { dur: 0.5, r: 70 },
};

export const REASONS: Record<number, string> = {
  1: 'bomb exploded',
  7: 'bomb defused',
  8: 'Ts eliminated',
  9: 'CTs eliminated',
  12: 'time ran out',
};

export const ACTIVE_JOB = new Set(['queued', 'running']);
export const OPENABLE = new Set(['ready', 'needs_model']);
