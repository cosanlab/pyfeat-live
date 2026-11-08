<script lang="ts">
  // One channel strip per person: colour + name, mute, solo, volume, and
  // meters for the three AUs most above their baseline right now.
  import VolumeX from '@lucide/svelte/icons/volume-x';
  import Volume2 from '@lucide/svelte/icons/volume-2';
  import Headphones from '@lucide/svelte/icons/headphones';
  import type { RosterEntry } from '../studio/engine';

  type Props = {
    roster: RosterEntry[];
    onMute: (slot: string, muted: boolean) => void;
    onSolo: (slot: string, solo: boolean) => void;
    onVolume: (slot: string, v: number) => void;
  };
  let { roster, onMute, onSolo, onVolume }: Props = $props();
</script>

<div class="space-y-2">
  {#if roster.length === 0}
    <div class="text-[11px] text-zinc-500">No faces yet.</div>
  {/if}
  {#each roster as p (p.slot)}
    <div class="rounded-md border border-zinc-800 bg-zinc-950/60 p-2 {p.muted ? 'opacity-60' : ''}">
      <div class="flex items-center gap-2">
        <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background: {p.color}"></span>
        <span class="text-[11.5px] text-zinc-200 truncate flex-1" title={p.label}>{p.label}</span>
        <button
          class="p-1 rounded border {p.muted ? 'border-red-500/40 text-red-400 bg-red-500/10' : 'border-zinc-800 text-zinc-400 hover:text-zinc-200'}"
          title={p.muted ? 'Unmute' : 'Mute'}
          aria-label={p.muted ? `Unmute ${p.label}` : `Mute ${p.label}`}
          onclick={() => onMute(p.slot, !p.muted)}
        >
          {#if p.muted}<VolumeX size={11} />{:else}<Volume2 size={11} />{/if}
        </button>
        <button
          class="p-1 rounded border {p.solo ? 'border-yellow-500/40 text-yellow-400 bg-yellow-500/10' : 'border-zinc-800 text-zinc-400 hover:text-zinc-200'}"
          title={p.solo ? 'Unsolo' : 'Solo'}
          aria-label={p.solo ? `Unsolo ${p.label}` : `Solo ${p.label}`}
          onclick={() => onSolo(p.slot, !p.solo)}
        >
          <Headphones size={11} />
        </button>
      </div>
      <input
        type="range" min="0" max="1" step="0.01" value={p.volume}
        class="w-full mt-1.5 accent-zinc-300 h-1"
        aria-label={`${p.label} volume`}
        oninput={(e) => onVolume(p.slot, Number((e.target as HTMLInputElement).value))}
      />
      {#if p.calibrating}
        <div class="mt-1 text-[10px] text-zinc-500">calibrating…</div>
      {:else}
        <div class="mt-1 space-y-0.5">
          {#each p.top as m (m.feature)}
            <div class="flex items-center gap-1.5">
              <span class="text-[9.5px] font-mono text-zinc-500 w-9">{m.feature}</span>
              <div class="flex-1 h-1 rounded bg-zinc-800 overflow-hidden">
                <div class="h-full rounded" style="width: {Math.min(100, (m.z / 4) * 100)}%; background: {p.color}"></div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/each}
</div>
