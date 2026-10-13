/** A [[tick, value], ...] change list as served by the API (sorted by tick). */
export type ChangeList<V> = ReadonlyArray<readonly [number, V]>;

/** Value of the last entry with tick <= t, or null when t precedes the list. */
export function changeAt<V>(list: ChangeList<V> | null | undefined, t: number): V | null {
  if (!list || !list.length) return null;
  let lo = 0;
  let hi = list.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (list[m]![0] <= t) {
      ans = m;
      lo = m + 1;
    } else hi = m - 1;
  }
  return ans < 0 ? null : list[ans]![1];
}

/** First index i with arr[i] >= t, clamped to the last index (0 for an empty array). */
export function lowerBound(arr: ArrayLike<number>, t: number): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (arr[m]! < t) lo = m + 1;
    else hi = m;
  }
  return Math.max(0, Math.min(lo, arr.length - 1));
}

/** Index of the last element with arr[i] <= t, or -1 (arr sorted ascending). */
export function lastAtOrBefore(arr: ArrayLike<number>, t: number): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (arr[m]! <= t) lo = m + 1;
    else hi = m;
  }
  return lo - 1;
}

/** Step-function lookup on parallel arrays: value at the last tick <= `tick` (first value if before). */
export function seriesP(ticks: ArrayLike<number>, ps: ArrayLike<number | null>, tick: number): number | null {
  if (!ticks.length) return null;
  const i = lowerBound(ticks, tick);
  const j = ticks[i]! > tick && i > 0 ? i - 1 : i;
  return ps[j] ?? null;
}
