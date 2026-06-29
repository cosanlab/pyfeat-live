// frontend/src/lib/experimental.svelte.ts
// Client-side experimental-feature flags. Persisted to localStorage and toggled
// only via the native macOS Settings menu (see App.svelte + tauri/src-tauri/src/lib.rs).
// Off by default so normal users never see the gated features.

const STORAGE_KEY = 'pyfeat:experimental';

// Single source of truth: adding a flag here makes it appear in the Settings
// modal and available for gating elsewhere.
export const FLAGS = [
  { id: 'generateLive', label: 'Generate · Live mode', desc: 'Webcam → live edited video' },
  { id: 'generateImage', label: 'Generate · Image mode', desc: 'Drop an image → edit' },
] as const;

export type FlagId = (typeof FLAGS)[number]['id'];

function defaults(): Record<FlagId, boolean> {
  return Object.fromEntries(FLAGS.map((f) => [f.id, false])) as Record<FlagId, boolean>;
}

function hydrate(): Record<FlagId, boolean> {
  const base = defaults();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    for (const f of FLAGS) {
      if (typeof parsed[f.id] === 'boolean') base[f.id] = parsed[f.id] as boolean;
    }
  } catch {
    /* missing/corrupt → defaults */
  }
  return base;
}

// Reactive store. Read `experimental.generateImage` etc. directly in components.
export const experimental = $state<Record<FlagId, boolean>>(hydrate());

// Set a flag and persist the whole object. Use this instead of mutating
// `experimental` directly so persistence always runs.
export function setFlag(id: FlagId, value: boolean): void {
  experimental[id] = value;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(experimental));
  } catch {
    /* storage unavailable → in-memory only */
  }
}
