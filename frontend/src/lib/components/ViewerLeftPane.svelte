<script lang="ts">
  import List from '@lucide/svelte/icons/list';
  import Bookmark from '@lucide/svelte/icons/bookmark';
  import SessionsList from './SessionsList.svelte';
  import AnnotationsList from './AnnotationsList.svelte';
  import type { SessionSummary, Annotation, AnnotationKind } from '../types';

  type Tab = 'sessions' | 'annotations';
  type FilterKind = 'all' | AnnotationKind;

  type Props = {
    activeTab: Tab;
    onTabChange: (t: Tab) => void;
    // sessions tab
    sessions: SessionSummary[];
    currentSessionId: string | null;
    sessionFilter: string;
    onSelectSession: (id: string) => void;
    onSessionFilterChange: (v: string) => void;
    // annotations tab
    annotations: Annotation[];
    currentAnnotationId: string | null;
    annotationFilter: FilterKind;
    onSelectAnnotation: (a: Annotation) => void;
    onAnnotationFilterChange: (f: FilterKind) => void;
    onAddAnnotationAtCurrentTime: () => void;
  };
  let {
    activeTab, onTabChange,
    sessions, currentSessionId, sessionFilter, onSelectSession, onSessionFilterChange,
    annotations, currentAnnotationId, annotationFilter, onSelectAnnotation,
    onAnnotationFilterChange, onAddAnnotationAtCurrentTime,
  }: Props = $props();
</script>

<aside class="w-[240px] bg-zinc-900 border-r border-zinc-900 flex flex-col h-full min-h-0">
  <div class="flex border-b border-zinc-900">
    <button
      class="flex-1 px-3 py-2.5 text-[11px] inline-flex items-center justify-center gap-1.5 border-b-2 {activeTab === 'sessions' ? 'border-green-500 text-zinc-50' : 'border-transparent text-zinc-500 hover:text-zinc-300'}"
      onclick={() => onTabChange('sessions')}
    >
      <List size={12} />
      Sessions
      <span class="text-[10px] px-1.5 rounded-full bg-zinc-800 text-zinc-300 font-mono">{sessions.length}</span>
    </button>
    <button
      class="flex-1 px-3 py-2.5 text-[11px] inline-flex items-center justify-center gap-1.5 border-b-2 {activeTab === 'annotations' ? 'border-green-500 text-zinc-50' : 'border-transparent text-zinc-500 hover:text-zinc-300'}"
      onclick={() => onTabChange('annotations')}
    >
      <Bookmark size={12} />
      Annotations
      <span class="text-[10px] px-1.5 rounded-full bg-zinc-800 text-zinc-300 font-mono">{annotations.length}</span>
    </button>
  </div>
  <div class="flex-1 overflow-hidden">
    {#if activeTab === 'sessions'}
      <SessionsList
        {sessions}
        currentId={currentSessionId}
        filter={sessionFilter}
        onSelect={onSelectSession}
        onFilterChange={onSessionFilterChange}
      />
    {:else}
      <AnnotationsList
        {annotations}
        {currentAnnotationId}
        filter={annotationFilter}
        onSelect={onSelectAnnotation}
        onFilterChange={onAnnotationFilterChange}
        onAddAtCurrentTime={onAddAnnotationAtCurrentTime}
      />
    {/if}
  </div>
</aside>
