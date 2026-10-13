import { defineStore } from 'pinia';
import { ref } from 'vue';

/** Which main view is showing. 'home' = the empty state card. */
export type MainView = 'home' | 'demo' | 'status';

/** An explicit message for the empty-state card (overrides the default copy). */
export interface Notice {
  title: string;
  message: string;
  /** shown as a code block under the message */
  detail?: string;
  isError: boolean;
}

export const useSessionStore = defineStore('session', () => {
  const view = ref<MainView>('home');
  const notice = ref<Notice | null>(null);

  function showNotice(n: Notice) {
    notice.value = n;
    view.value = 'home';
  }

  /** bumped to remount (and refetch) the status page */
  const statusNonce = ref(0);
  function showStatus() {
    notice.value = null;
    statusNonce.value++;
    view.value = 'status';
  }

  function goHome() {
    notice.value = null;
    view.value = 'home';
  }

  return { view, notice, statusNonce, showNotice, showStatus, goHome };
});
