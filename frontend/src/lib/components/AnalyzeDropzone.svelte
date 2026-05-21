<script lang="ts">
  import Upload from '@lucide/svelte/icons/upload';

  type Props = {
    onFiles: (files: File[]) => void;
    activePresetName: string | null;
  };
  let { onFiles, activePresetName }: Props = $props();

  let dragOver = $state(false);

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    if (!e.dataTransfer) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) onFiles(files);
  }

  function handleBrowse() {
    // The input must be attached to the DOM for the file picker to open
    // in WKWebView (a detached element's .click() is a no-op there).
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.mp4,.mov,.jpg,.jpeg,.png';
    input.style.position = 'fixed';
    input.style.left = '-9999px';
    document.body.appendChild(input);
    input.onchange = () => {
      if (input.files && input.files.length > 0) {
        onFiles(Array.from(input.files));
      }
      input.remove();
    };
    input.click();
  }
</script>

<div
  role="presentation"
  class="border border-dashed rounded-lg p-4 text-center transition {dragOver ? 'border-green-400 bg-green-500/5' : 'border-zinc-700 bg-zinc-900/50'}"
  ondrop={handleDrop}
  ondragover={(e) => { e.preventDefault(); dragOver = true; }}
  ondragleave={() => { dragOver = false; }}
>
  <Upload class="mx-auto text-zinc-500 mb-1" size={22} />
  <h3 class="text-[12.5px] font-medium text-zinc-50">Drop files to add to queue</h3>
  <p class="text-[11px] text-zinc-500 mt-0.5">
    or <button class="text-green-400" onclick={handleBrowse}>browse</button>
  </p>
  {#if activePresetName}
    <div class="mt-2 inline-block px-2 py-0.5 rounded text-[10.5px] font-mono bg-zinc-900 text-zinc-400">
      <span class="inline-block w-1.5 h-1.5 rounded-full bg-green-400 align-middle mr-1"></span>
      uses preset: <span class="text-green-400">{activePresetName}</span>
    </div>
  {/if}
</div>
