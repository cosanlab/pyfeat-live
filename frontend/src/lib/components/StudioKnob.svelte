<script lang="ts">
  // A rotary knob for the synth view. Drag up/down (Shift = fine), arrow
  // keys, or double-click to let the control go back to automatic. Coloured
  // dots on the rim show each person's live value (knob + face signals).
  type Props = {
    /** Knob position 0..1, or undefined when the knob has not been set. */
    value: number | undefined;
    /** Where the control rests when nothing sets it (drawn for an unset knob). */
    neutral: number;
    live?: { color: string; value: number }[];
    label: string;
    hint?: string;
    lo?: string;
    hi?: string;
    onChange: (v: number | undefined) => void;
  };
  let { value, neutral, live = [], label, hint = '', lo = '', hi = '', onChange }: Props = $props();

  const SIZE = 56, C = SIZE / 2, R = 19, RIM = 25;
  const A0 = -135, SPAN = 270;
  const pt = (r: number, v: number): [number, number] => {
    const a = ((A0 + SPAN * Math.max(0, Math.min(1, v))) * Math.PI) / 180;
    return [C + r * Math.sin(a), C - r * Math.cos(a)];
  };
  const arc = (r: number, from: number, to: number) => {
    const [x0, y0] = pt(r, from), [x1, y1] = pt(r, to);
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${(to - from) * SPAN > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  const shown = $derived(value ?? neutral);
  const tip = $derived(pt(R - 5, shown));
  const text = $derived(value === undefined ? 'automatic' : `${Math.round(value * 100)}%`);

  let dragging = $state(false);
  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    e.preventDefault();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    el.focus();
    const y0 = e.clientY, v0 = shown;
    let moved = false;
    dragging = true;
    const move = (ev: PointerEvent) => {
      const dy = y0 - ev.clientY;
      if (!moved && Math.abs(dy) < 3) return; // a click is not a change
      moved = true;
      onChange(Math.max(0, Math.min(1, v0 + dy / (ev.shiftKey ? 600 : 150))));
    };
    const up = () => {
      dragging = false;
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  }
  function key(e: KeyboardEvent) {
    const step = e.shiftKey ? 0.01 : 0.05;
    let v: number | undefined | null = null;
    if (e.key === 'ArrowUp' || e.key === 'ArrowRight') v = Math.min(1, shown + step);
    else if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') v = Math.max(0, shown - step);
    else if (e.key === 'Home') v = 0;
    else if (e.key === 'End') v = 1;
    else if (e.key === 'Delete' || e.key === 'Backspace') v = undefined;
    if (v === null) return;
    e.preventDefault();
    onChange(v);
  }
</script>

<div
  class="relative shrink-0 rounded-full outline-none touch-none select-none focus-visible:ring-1 focus-visible:ring-zinc-400 {dragging ? 'cursor-grabbing' : 'cursor-grab'}"
  style="width: {SIZE}px; height: {SIZE}px;"
  role="slider" tabindex="0"
  aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(shown * 100)} aria-valuetext={text}
  title={`${label}${hint ? `: ${hint}` : ''}${lo ? ` (${lo} ↔ ${hi})` : ''}. Drag up or down; double-click for automatic.`}
  onpointerdown={down} onkeydown={key} ondblclick={() => onChange(undefined)}
>
  <svg width={SIZE} height={SIZE} viewBox="0 0 {SIZE} {SIZE}" aria-hidden="true">
    <path d={arc(R, 0, 1)} fill="none" stroke="#3f3f46" stroke-width="3" stroke-linecap="round" />
    {#if value !== undefined && value > 0.005}
      <path d={arc(R, 0, value)} fill="none" stroke="#e4e4e7" stroke-width="3" stroke-linecap="round" />
    {/if}
    <circle cx={C} cy={C} r={R - 6} fill="#18181b" stroke="#52525b" stroke-width="1" />
    <line x1={C} y1={C} x2={tip[0]} y2={tip[1]} stroke={value === undefined ? '#71717a' : '#fafafa'} stroke-width="2" stroke-linecap="round"
      stroke-dasharray={value === undefined ? '2 2.5' : undefined} />
    {#each live as l, i (i)}
      {@const [x, y] = pt(RIM, l.value)}
      <circle cx={x} cy={y} r="2.6" fill={l.color} stroke="#09090b" stroke-width="0.8" />
    {/each}
  </svg>
</div>
