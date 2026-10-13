import { onBeforeUnmount, onMounted, ref, shallowRef, watch, type Ref, type ShallowRef } from 'vue';
import { sizeCanvas, type CanvasSize } from '@/lib/canvas';

const dpr = ref(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1);
let dprListeners = 0;
const onDpr = () => {
  dpr.value = window.devicePixelRatio || 1;
};

/**
 * Keep a canvas sized (in CSS px) to `size()`, with a devicePixelRatio backing store.
 * Returns the context scaled to CSS pixels, or null while the canvas or size is unknown.
 */
export function useCanvas(
  canvas: Ref<HTMLCanvasElement | null>,
  size: () => { w: number; h: number } | null,
): ShallowRef<CanvasSize | null> {
  const out = shallowRef<CanvasSize | null>(null);
  onMounted(() => {
    if (dprListeners++ === 0) window.addEventListener('resize', onDpr);
  });
  onBeforeUnmount(() => {
    if (--dprListeners === 0) window.removeEventListener('resize', onDpr);
  });
  watch(
    [canvas, () => size()?.w, () => size()?.h, dpr],
    () => {
      const cv = canvas.value;
      const s = size();
      out.value = cv && s && s.w > 0 && s.h > 0 ? sizeCanvas(cv, s.w, s.h, dpr.value) : null;
    },
    { immediate: true, flush: 'post' },
  );
  return out;
}

/** Content-box width of an element, tracked with a ResizeObserver. */
export function useElementWidth(el: Ref<HTMLElement | null>): Ref<number> {
  const width = ref(0);
  let ro: ResizeObserver | null = null;
  onMounted(() => {
    ro = new ResizeObserver(() => {
      if (el.value) width.value = el.value.clientWidth;
    });
    watch(
      el,
      (node, prev) => {
        if (prev) ro?.unobserve(prev);
        if (node) {
          ro?.observe(node);
          width.value = node.clientWidth;
        }
      },
      { immediate: true },
    );
  });
  onBeforeUnmount(() => ro?.disconnect());
  return width;
}
