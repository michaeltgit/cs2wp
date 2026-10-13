import { markRaw } from 'vue';
import { api } from '@/api/client';

/** Radar background for a map: density outline drawn from where players stood + bomb sites. */
export interface MapAsset {
  bounds: [number, number, number, number] | null;
  sites: Record<string, [number, number]>;
  img: HTMLCanvasElement | null;
}

const cache = new Map<string, Promise<MapAsset>>();

/** Decode the base64 density grid into an offscreen canvas (light-grey, alpha = density). */
export function decodeDensity(grid: string, size: number): HTMLCanvasElement | null {
  const bin = atob(grid);
  const img = document.createElement('canvas');
  img.width = img.height = size;
  const ictx = img.getContext('2d');
  if (!ictx) return null;
  const data = ictx.createImageData(size, size);
  for (let i = 0; i < size * size && i < bin.length; i++) {
    const v = bin.charCodeAt(i);
    data.data[i * 4] = 180;
    data.data[i * 4 + 1] = 190;
    data.data[i * 4 + 2] = 210;
    data.data[i * 4 + 3] = Math.round((v / 255) * 0.8 * 255);
  }
  ictx.putImageData(data, 0, 0);
  return img;
}

/** Fetch (once per map name) and decode the map background. Never rejects. */
export function loadMapAsset(name: string): Promise<MapAsset> {
  let p = cache.get(name);
  if (!p) {
    p = api
      .map(name)
      .then((m) =>
        markRaw<MapAsset>({ bounds: m.bounds, sites: m.sites || {}, img: decodeDensity(m.grid, m.size || 256) }),
      )
      .catch(() => markRaw<MapAsset>({ bounds: null, sites: {}, img: null }));
    cache.set(name, p);
  }
  return p;
}
