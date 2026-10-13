import { onBeforeUnmount, onMounted } from 'vue';
import { TICKRATE } from '@/lib/constants';

export type KeyAction =
  | { kind: 'toggle' }
  | { kind: 'seek'; ticks: number }
  | { kind: 'round'; delta: number };

/** Map a key press to a playback action (null = not ours). */
export function keyAction(key: string, shift: boolean): KeyAction | null {
  switch (key) {
    case ' ':
      return { kind: 'toggle' };
    case 'ArrowLeft':
      return shift ? { kind: 'round', delta: -1 } : { kind: 'seek', ticks: -5 * TICKRATE };
    case 'ArrowRight':
      return shift ? { kind: 'round', delta: 1 } : { kind: 'seek', ticks: 5 * TICKRATE };
    case ',':
    case '<':
      return { kind: 'seek', ticks: -1 };
    case '.':
    case '>':
      return { kind: 'seek', ticks: 1 };
    default:
      return null;
  }
}

const TYPING = 'input[type=text], input[type=search], textarea, select';

/**
 * Global playback shortcuts: Space play/pause, ←/→ 5 s, Shift+←/→ previous/next round,
 * , / . one tick. Ignored while typing and with Cmd/Ctrl/Alt held.
 */
export function useKeyboard(opts: { enabled: () => boolean; run: (a: KeyAction) => void }): void {
  const onKey = (e: KeyboardEvent) => {
    const t = e.target as Element | null;
    if (t && typeof t.closest === 'function' && t.closest(TYPING)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (!opts.enabled()) return;
    const a = keyAction(e.key, e.shiftKey);
    if (!a) return;
    opts.run(a);
    e.preventDefault();
    if (t instanceof HTMLButtonElement) t.blur(); // stop Space from also clicking a focused button
  };
  onMounted(() => window.addEventListener('keydown', onKey));
  onBeforeUnmount(() => window.removeEventListener('keydown', onKey));
}
