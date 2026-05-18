// Shared reactive state via Svelte 5 runes. Import these and read /
// write directly; components automatically re-render on change.

import type { ComputeInfo } from './api';

export const systemStore = $state<{
  compute: ComputeInfo | null;
  health: 'unknown' | 'ok' | 'error';
}>({
  compute: null,
  health: 'unknown',
});
