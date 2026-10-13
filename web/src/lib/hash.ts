/** Deep links: #demo=ID&round=N */
export interface DeepLink {
  demo: string;
  round: number | null;
}

export function parseDeepLink(hash: string): DeepLink | null {
  const h = new URLSearchParams(hash.replace(/^#/, ''));
  const demo = h.get('demo');
  if (!demo) return null;
  const r = h.get('round');
  const round = r != null && r !== '' && Number.isFinite(Number(r)) ? Number(r) : null;
  return { demo, round };
}

export const deepLinkHash = (demo: string, round: number): string => `#demo=${encodeURIComponent(demo)}&round=${round}`;
