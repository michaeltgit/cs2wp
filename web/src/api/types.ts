// Response shapes of the cs2-winprob FastAPI backend (src/cs2_winprob/api.py).
// Numbers that the backend may emit as NaN are typed `number | null` (parseJSON maps NaN to null).

export type ChangeList<V> = [number, V][];

// ---------- demos & jobs ----------
export interface DemoScore {
  ct_side_end: number;
  t_side_end: number;
}

/** new | parsing | features | scoring | ready | needs_model | failed */
export type DemoStatus = string;

export interface DemoSummary {
  id: string;
  filename: string | null;
  sha1?: string | null;
  map: string | null;
  status: DemoStatus;
  error: string | null;
  n_rounds: number | null;
  score: DemoScore | null;
  created_at: number;
  kalshi_ticker?: string | null;
  kalshi_status?: string | null;
  kalshi_confidence?: string | null;
  score_model?: string | null;
  score_kind?: string | null;
}

/** queued | running | done | failed */
export type JobStatus = string;

export interface Job {
  id: string;
  demo_id: string | null;
  /** process | ingest | train | rescore */
  kind: string;
  status: JobStatus;
  stage: string | null;
  message: string | null;
  created_at: number;
  updated_at: number | null;
}

export interface JobRef {
  job_id: string;
}

export interface ActivateResponse extends JobRef {
  active: string;
}

// ---------- demo detail ----------
export interface RoundMeta {
  round: number;
  freeze_end: number;
  end: number;
  winner: number | null;
  reason: number | null;
  valid: boolean;
  ct_players?: string[];
  t_players?: string[];
  a_is_ct?: boolean;
  a_score?: number;
  b_score?: number;
  ct_score: number;
  t_score: number;
  p_ct_start?: number | null;
}

export interface TeamInfo {
  name: string;
  steamids?: string[];
}

export interface Teams {
  a: TeamInfo;
  b: TeamInfo;
}

export interface WpaPlayer {
  steamid: string;
  name: string;
  wpa: number;
  kills: number;
  deaths: number;
  plants: number;
  defuses: number;
}

export interface Wpa {
  model: string | null;
  /** out-of-sample | in-sample | unknown */
  kind?: string | null;
  players: WpaPlayer[];
}

export interface DemoDetail {
  demo_id?: string;
  map: string | null;
  tickrate?: number;
  players?: { steamid: string; name: string }[];
  rounds: RoundMeta[];
  teams?: Teams | null;
  wpa: Wpa | null;
}

// ---------- round data (columnar, one entry per tick) ----------
export interface RoundPlayer {
  steamid: string;
  name: string;
  team: number;
  x: (number | null)[];
  y: (number | null)[];
  yaw: (number | null)[];
  hp: number[];
  alive: number[];
  armor: ChangeList<number | null>;
  weapon: ChangeList<string | null>;
  has_bomb: ChangeList<boolean | null>;
  money: ChangeList<number | null>;
  equip?: ChangeList<number | null>;
}

export interface RoundEvent {
  tick: number;
  /** kill | plant | defuse_start | defuse | explode | smoke | molotov | flash | he | ... */
  type: string;
  actor_name?: string | null;
  actor_steamid?: string | null;
  actor_team?: number | null;
  victim_name?: string | null;
  victim_steamid?: string | null;
  victim_team?: number | null;
  weapon?: string | null;
  headshot?: boolean | null;
  x?: number | null;
  y?: number | null;
  p_before?: number | null;
  p_after?: number | null;
  swing_ct?: number | null;
}

export interface RoundData {
  round: RoundMeta;
  tickrate: number;
  ticks: number[];
  p_ct: (number | null)[];
  players: RoundPlayer[];
  events: RoundEvent[];
}

export interface MapInfo {
  map: string;
  n_demos: number;
  bounds: [number, number, number, number];
  size: number;
  /** base64 of size*size uint8 densities, row 0 = top (max y) */
  grid: string;
  sites: Record<string, [number, number]>;
}

// ---------- models ----------
export interface MetricSet {
  log_loss?: number | null;
  brier?: number | null;
  ece?: number | null;
  accuracy?: number | null;
}

export interface OverallMetrics {
  baseline?: MetricSet;
  lightgbm?: MetricSet;
  lightgbm_calibrated?: MetricSet;
}

export interface ModelMetrics {
  held_out?: boolean;
  overall?: OverallMetrics;
  feature_importance?: Record<string, number>;
  [key: string]: unknown;
}

export interface ModelVersion {
  created?: number | string | null;
  n_demos?: number | string | null;
  n_rounds?: number | string | null;
  held_out?: boolean | null;
  overall?: OverallMetrics;
  metrics?: ModelMetrics;
}

export interface ModelRegistry {
  active: string | null;
  versions: Record<string, ModelVersion>;
}

// ---------- data status ----------
export interface StatusMap {
  id: string;
  map: string | null;
  status: string;
  rounds: number | null;
  kalshi: string | null;
  ticker: string | null;
  alignment: string | null;
  scored_by: string | null;
  score_kind: string | null;
  error: string | null;
}

export interface StatusMatch {
  match: string;
  maps: StatusMap[];
  first_seen: number;
}

export interface StatusSummary {
  matches: number;
  maps: number;
  ready: number;
  failed: number;
  kalshi_linked: number;
  kalshi_no_market: number;
  alignment: { good: number; weak: number; bad: number; none: number };
  out_of_sample: number;
  in_sample: number;
}

export interface StatusResponse {
  summary: StatusSummary;
  matches: StatusMatch[];
}

// ---------- map win probability + Kalshi ----------
export interface MapWinSeries {
  teams: Teams | null;
  tick: number[];
  round: number[];
  p_map_a: (number | null)[];
}

export type YesTeam = 'a' | 'b';

export interface KalshiMarketPoint {
  sec: number;
  tick: number;
  mid_a: number | null;
  bid_a: number | null;
  ask_a: number | null;
  volume?: number | null;
}

export interface KalshiComparison {
  demo_id: string;
  ticker: string;
  series?: string;
  title?: string | null;
  yes_team: YesTeam;
  start_ts: number;
  result?: string | null;
  aligned_by?: string | null;
  linked_at?: number;
  teams?: Teams | null;
  market: KalshiMarketPoint[];
  ours_per_minute?: { sec: number; p_map_a: number | null }[];
  mean_abs_gap: number | null;
  n_compared: number;
}

export interface KalshiAlignment {
  /** good | weak | bad | none | unlinked */
  confidence?: string | null;
  reason?: string;
  n_events?: number;
  pre_move?: number | null;
  post_move?: number | null;
  best_offset_s?: number | null;
  best_move?: number | null;
  sharpness?: number | null;
}

export interface KalshiDisagreement {
  round: number;
  tick: number;
  round_secs: number;
  ours: number;
  market: number;
  gap: number;
  score: string;
}

/** `{n_seconds: 0}` when the market and the map do not overlap. */
export interface KalshiAnalysis {
  n_seconds: number;
  ticker?: string;
  teams?: Teams | null;
  final?: string;
  team_a_won?: boolean;
  n_trades?: number;
  aligned_by?: string | null;
  start_ts?: number;
  mean_abs_gap?: number;
  mean_gap?: number;
  level_corr?: number | null;
  brier_ours?: number;
  brier_market?: number;
  lag_secs?: number | null;
  lag_corr?: number | null;
  alignment?: KalshiAlignment;
  disagreements?: KalshiDisagreement[];
}

export interface KalshiRoundTrades {
  ticker: string;
  yes_team: YesTeam;
  tick: number[];
  price_a: number[];
  count: number[];
  ts: number[];
}

// ---------- live WebSocket (/ws/live/{demo}/{round}) ----------
export interface LiveHello {
  type: 'hello';
  session: string;
  first_tick: number;
  last_tick: number;
  model: string | null;
}

export interface LivePlayer {
  steamid: string;
  name: string;
  team: number;
  x: number | null;
  y: number | null;
  yaw: number | null;
  hp: number;
  armor: number | null;
  weapon: string | null;
  money: number | null;
  has_bomb: boolean;
  alive: boolean;
}

export interface LiveFrame {
  type: 'frame';
  tick: number;
  p_ct: number | null;
  series?: [number, number | null][];
  players: LivePlayer[];
  model?: string | null;
}

export interface LiveError {
  type: 'error';
  message: string;
}

export type LiveMessage = LiveHello | LiveFrame | LiveError;

export type LiveCommand =
  | { cmd: 'play' }
  | { cmd: 'pause' }
  | { cmd: 'seek'; tick: number }
  | { cmd: 'speed'; value: number };

