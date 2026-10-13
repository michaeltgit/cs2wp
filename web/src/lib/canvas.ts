export interface CanvasSize {
  ctx: CanvasRenderingContext2D;
  w: number;
  h: number;
  dpr: number;
}

/** Size a canvas for devicePixelRatio; returns a context already scaled to CSS pixels. */
export function sizeCanvas(cv: HTMLCanvasElement, w: number, h: number, dpr = window.devicePixelRatio || 1): CanvasSize | null {
  cv.width = Math.max(1, Math.round(w * dpr));
  cv.height = Math.max(1, Math.round(h * dpr));
  cv.style.width = `${w}px`;
  cv.style.height = `${h}px`;
  const ctx = cv.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h, dpr };
}
