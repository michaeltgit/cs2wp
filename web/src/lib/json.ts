/**
 * Parse JSON from the API. Python's json module emits bare NaN / Infinity, which is not valid
 * JSON; on a parse failure those tokens are replaced with null and parsing is retried.
 */
export function parseJSON<T = unknown>(text: string): T {
  try {
    return JSON.parse(text) as T;
  } catch {
    return JSON.parse(text.replace(/([:[,]\s*)-?(NaN|Infinity)\b/g, '$1null')) as T;
  }
}
