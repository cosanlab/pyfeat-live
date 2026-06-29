<!-- 2D joystick for gaze: drag the dot, the eyes follow. x -> yaw, y -> pitch. -->
<script lang="ts">
  let { yaw, pitch, maxYaw = 30, maxPitch = 25, onChange }: {
    yaw: number; pitch: number; maxYaw?: number; maxPitch?: number;
    onChange: (g: { yaw: number; pitch: number }) => void;
  } = $props();

  let pad: HTMLDivElement;
  let dragging = $state(false);

  // knob position (% of pad) from the current gaze
  const kx = $derived(50 + (yaw / maxYaw) * 50);
  const ky = $derived(50 + (-pitch / maxPitch) * 50);   // up on the pad = look up

  function update(clientX: number, clientY: number) {
    const r = pad.getBoundingClientRect();
    let nx = ((clientX - r.left) / r.width) * 2 - 1;
    let ny = ((clientY - r.top) / r.height) * 2 - 1;
    const m = Math.hypot(nx, ny);
    if (m > 1) { nx /= m; ny /= m; }                    // clamp to the circle
    onChange({ yaw: Math.round(nx * maxYaw), pitch: Math.round(-ny * maxPitch) });
  }
  function down(e: PointerEvent) { dragging = true; pad.setPointerCapture(e.pointerId); update(e.clientX, e.clientY); }
  function move(e: PointerEvent) { if (dragging) update(e.clientX, e.clientY); }
  function up() { dragging = false; }
</script>

<div bind:this={pad} role="slider" aria-label="gaze direction" tabindex="0"
     aria-valuenow={yaw}
     class="relative mx-auto h-28 w-28 rounded-full bg-zinc-950 border border-zinc-800 cursor-pointer select-none touch-none"
     onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
  <div class="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-zinc-800/70"></div>
  <div class="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-zinc-800/70"></div>
  <div class="absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-green-300 bg-green-500 pointer-events-none transition-[box-shadow] {dragging ? 'ring-2 ring-green-500/30' : ''}"
       style="left:{kx}%; top:{ky}%;"></div>
</div>
