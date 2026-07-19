<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { RpaAgentCreationStepViewModel } from '@/utils/rpaAgentCreationProjection';

const props = withDefaults(defineProps<{
  steps: RpaAgentCreationStepViewModel[];
  title?: string;
  mode?: string;
  isRecording?: boolean;
  autoScroll?: boolean;
  emptyMessage?: string;
}>(), { title: '录制步骤', isRecording: false, autoScroll: false, emptyMessage: '操作浏览器或提交指令后，步骤会立即出现在这里。' });

const scroller = ref<HTMLElement | null>(null);
const rows = computed(() => props.steps);
const executionLabel: Record<RpaAgentCreationStepViewModel['executionStatus'], string> = {
  queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消',
};
const executionClass: Record<RpaAgentCreationStepViewModel['executionStatus'], string> = {
  queued: 'bg-slate-100 text-slate-600', running: 'bg-blue-50 text-blue-700', succeeded: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700', cancelled: 'bg-amber-50 text-amber-700',
};
const replayLabel: Record<RpaAgentCreationStepViewModel['replayStatus'], string> = {
  pending: '待评估', deterministic_ready: '可确定回放', insufficient_evidence: '运行时 AI', needs_confirmation: '需确认',
};

watch(() => props.steps.length, async () => {
  if (!props.autoScroll) return;
  await nextTick();
  scroller.value?.lastElementChild?.scrollIntoView({ block: 'nearest' });
});
</script>

<template>
  <section class="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--background-gray-main)]">
    <header class="flex items-center justify-between px-4 py-3">
      <div><h2 class="font-extrabold">{{ title }}</h2><p class="text-[11px] text-[var(--text-tertiary)]">手工动作与 AI 意图按提交顺序排列</p></div>
      <span class="rounded-md bg-[var(--background-white-main)] px-2 py-1 text-xs font-bold text-[var(--text-brand)]">{{ rows.length }} 项</span>
    </header>
    <div ref="scroller" class="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 pb-4" aria-live="polite">
      <article v-for="step in rows" :key="step.id" class="rounded-lg border border-[var(--border-main)] bg-[var(--background-white-main)] p-3">
        <div class="flex items-start gap-2">
          <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--fill-tsp-gray-main)] text-[10px] font-extrabold">{{ String(step.ordinal).padStart(2, '0') }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="rounded px-1.5 py-0.5 text-[10px] font-bold text-[var(--text-secondary)]">{{ step.kind === 'manual' ? '手工' : 'AI' }}</span>
              <span class="rounded px-1.5 py-0.5 text-[10px] font-bold" :class="executionClass[step.executionStatus]">{{ executionLabel[step.executionStatus] }}</span>
            </div>
            <h3 class="mt-1 text-sm font-extrabold text-[var(--text-primary)]">{{ step.title }}</h3>
            <p class="mt-1 text-[11px] text-[var(--text-tertiary)]">{{ replayLabel[step.replayStatus] }}<span v-if="step.compileMode"> · {{ step.compileMode === 'playwright' ? 'Playwright' : 'Agent' }}</span></p>
            <ul v-if="step.observations.length" class="mt-2 space-y-1 rounded-md bg-[var(--background-gray-main)] p-2">
              <li v-for="observation in step.observations" :key="observation.trace_id" class="text-[11px] text-[var(--text-secondary)]">{{ observation.summary }}</li>
            </ul>
          </div>
        </div>
      </article>
      <div v-if="!rows.length" class="rounded-lg bg-[var(--background-white-main)] p-8 text-center text-sm text-[var(--text-tertiary)]">{{ emptyMessage }}</div>
      <div v-if="isRecording" class="py-2 text-center text-xs font-semibold text-[var(--text-brand)]">正在观察新操作</div>
    </div>
  </section>
</template>
