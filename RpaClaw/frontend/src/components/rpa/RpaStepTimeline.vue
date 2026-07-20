<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { Bot, ChevronDown, ChevronUp, Loader2, Radio, Wand2 } from 'lucide-vue-next';
import type { RpaAgentCreationStepViewModel } from '@/utils/rpaAgentCreationProjection';

const props = withDefaults(defineProps<{
  steps: RpaAgentCreationStepViewModel[];
  title?: string;
  mode?: 'record' | 'configure' | 'test';
  isRecording?: boolean;
  autoScroll?: boolean;
  emptyMessage?: string;
  showHeader?: boolean;
}>(), {
  title: '录制步骤', mode: 'record', isRecording: false, autoScroll: false,
  emptyMessage: '当前没有步骤。', showHeader: true,
});

const scroller = ref<HTMLElement | null>(null);
const expandedId = ref<string | null>(null);
const rows = computed(() => props.steps);
const executionLabel: Record<RpaAgentCreationStepViewModel['executionStatus'], string> = {
  queued: '排队中', running: '执行中', succeeded: '已完成', failed: '执行失败', cancelled: '已取消',
};
const executionClass: Record<RpaAgentCreationStepViewModel['executionStatus'], string> = {
  queued: 'bg-slate-100 text-slate-600', running: 'bg-violet-50 text-[#831bd7]',
  succeeded: 'bg-emerald-50 text-emerald-700', failed: 'bg-rose-50 text-rose-700',
  cancelled: 'bg-amber-50 text-amber-700',
};
const replayLabel: Record<RpaAgentCreationStepViewModel['replayStatus'], string> = {
  pending: '待评估', deterministic_ready: '可确定回放', insufficient_evidence: '运行时 AI', needs_confirmation: '需确认',
};
const actionLabel = (step: RpaAgentCreationStepViewModel) => step.kind === 'manual' ? '手工' : 'AI 操作';
const toggle = (id: string) => { expandedId.value = expandedId.value === id ? null : id; };

watch(() => props.steps.length, async () => {
  if (!props.autoScroll) return;
  await nextTick();
  scroller.value?.lastElementChild?.scrollIntoView({ block: 'nearest' });
});
</script>

<template>
  <section class="flex min-h-0 flex-1 flex-col overflow-hidden bg-[#eff1f2] dark:bg-[#212122]">
    <header v-if="showHeader" class="shrink-0 px-3 pb-2.5 pt-4">
      <div class="flex items-center justify-between gap-3">
        <div class="min-w-0"><h2 class="text-base font-extrabold">{{ title }}</h2><p class="mt-0.5 truncate text-[11px] font-medium text-gray-500">默认显示业务摘要，展开查看执行证据</p></div>
        <div class="flex shrink-0 items-center gap-2">
          <span v-if="isRecording" class="inline-flex items-center gap-1 rounded-md bg-violet-50 px-2 py-1 text-[10px] font-bold text-[#831bd7]"><Radio :size="11" class="animate-pulse" />自动跟随</span>
          <span class="rounded-md bg-white px-2 py-1 text-[10px] font-extrabold text-[#831bd7] dark:bg-[#272728]">{{ rows.length }} 步</span>
        </div>
      </div>
    </header>
    <div ref="scroller" class="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-1.5 pb-4" aria-live="polite">
      <article v-for="step in rows" :key="step.id" class="group relative overflow-hidden rounded-lg bg-white transition-colors dark:bg-[#272728]" :class="expandedId === step.id ? 'ring-2 ring-violet-100' : 'hover:bg-[#fbfbfc]'">
        <button type="button" class="block w-full px-2 py-2 text-left" :aria-expanded="expandedId === step.id" @click="toggle(step.id)">
          <div class="flex min-w-0 items-start gap-1.5 pr-5">
            <span class="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md bg-[#edeef0] text-[9px] font-extrabold text-gray-600">{{ String(step.ordinal).padStart(2, '0') }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1">
                <span class="inline-flex items-center gap-0.5 rounded bg-[#edeef0] px-1 py-0.5 text-[10px] font-bold text-gray-600"><Bot v-if="step.kind === 'ai_instruction'" :size="10" />{{ actionLabel(step) }}</span>
                <span class="rounded px-1 py-0.5 text-[10px] font-bold" :class="executionClass[step.executionStatus]">{{ executionLabel[step.executionStatus] }}</span>
                <span v-if="step.compileMode" class="rounded bg-purple-50 px-1 py-0.5 text-[10px] font-bold text-purple-700">{{ step.compileMode === 'playwright' ? 'Playwright' : 'Agent' }}</span>
              </div>
              <h3 class="mt-1 line-clamp-2 break-words text-[13px] font-extrabold leading-[18px]">{{ step.title }}</h3>
              <p class="mt-0.5 truncate text-[11px] text-gray-500">{{ replayLabel[step.replayStatus] }}<span v-if="step.observations.length"> · {{ step.observations.length }} 条动作证据</span></p>
            </div>
          </div>
        </button>
        <span class="pointer-events-none absolute right-1.5 top-2 text-gray-400"><ChevronUp v-if="expandedId === step.id" :size="14" /><ChevronDown v-else :size="14" /></span>
        <div v-if="expandedId === step.id" data-testid="timeline-details" class="space-y-2 bg-[#f7f4fa] px-2.5 pb-2.5 pt-2 dark:bg-[#342f3a]">
          <div class="rounded-lg bg-white p-2.5 text-[11px] dark:bg-[#272728]">
            <p class="font-bold">执行与回放</p><p class="mt-1 text-gray-500">{{ step.validation.details }} · {{ replayLabel[step.replayStatus] }}</p>
            <ul v-if="step.observations.length" class="mt-2 space-y-1 border-t pt-2"><li v-for="observation in step.observations" :key="observation.trace_id" class="break-words">{{ observation.summary }}</li></ul>
            <p v-else class="mt-2 border-t pt-2 text-gray-400">暂时没有动作证据。</p>
          </div>
        </div>
      </article>
      <div v-if="!rows.length" class="flex flex-col items-center justify-center gap-3 rounded-xl bg-white py-10 text-center text-gray-400 dark:bg-[#272728]"><Loader2 v-if="mode === 'test'" :size="20" class="animate-spin text-[#831bd7]" /><Wand2 v-else :size="20" class="text-[#831bd7]" /><p class="px-4 text-xs font-medium">{{ emptyMessage }}</p></div>
      <div v-if="isRecording" class="flex flex-col items-center justify-center gap-2 rounded-xl bg-white/60 py-5 text-center"><Wand2 :size="18" class="animate-pulse text-[#831bd7]" /><p class="text-xs font-semibold text-gray-500">检测新操作中...</p></div>
    </div>
  </section>
</template>

<style scoped>@media (prefers-reduced-motion: reduce) { .animate-pulse, .animate-spin { animation: none; } }</style>
