<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';

export interface RpaAgentTimelineViewModel {
  id: string;
  status: 'pending' | 'accepted' | 'rejected' | 'deleted' | 'effect' | 'running' | 'succeeded' | 'failed';
  title: string;
  label: string;
  parentId?: string | null;
  isEffect?: boolean;
  description?: string;
  diagnostic?: string;
}

const props = withDefaults(defineProps<{
  steps: RpaAgentTimelineViewModel[];
  title?: string;
  isRecording?: boolean;
  autoScroll?: boolean;
  emptyMessage?: string;
}>(), { title: '录制步骤', isRecording: false, autoScroll: false, emptyMessage: '当前没有步骤。' });

const scroller = ref<HTMLElement | null>(null);
const rows = computed(() => props.steps);
const statusLabel: Record<RpaAgentTimelineViewModel['status'], string> = {
  pending: '待结算', accepted: '已确认', rejected: '已拒绝', deleted: '已删除', effect: '副作用',
  running: '执行中', succeeded: '已完成', failed: '执行失败',
};
const statusClass: Record<RpaAgentTimelineViewModel['status'], string> = {
  pending: 'bg-violet-50 text-violet-700', accepted: 'bg-emerald-50 text-emerald-700', rejected: 'bg-rose-50 text-rose-700',
  deleted: 'bg-gray-100 text-gray-500', effect: 'bg-amber-50 text-amber-700', running: 'bg-violet-50 text-violet-700',
  succeeded: 'bg-emerald-50 text-emerald-700', failed: 'bg-rose-50 text-rose-700',
};
const actionLabel: Record<string, string> = { click: '点击', fill: '输入', set_checked: '勾选', select_option: '选择', navigate: '导航', extract: '提取', agent: 'Agent', effect: '副作用' };

watch(() => props.steps.length, async () => {
  if (!props.autoScroll) return;
  await nextTick(); scroller.value?.lastElementChild?.scrollIntoView({ block: 'nearest' });
});
</script>

<template>
  <section class="flex h-full min-h-0 flex-col overflow-hidden bg-[#eff1f2] dark:bg-[#212122]">
    <header class="flex items-center justify-between px-4 py-3">
      <div><h2 class="font-extrabold">{{ title }}</h2><p class="text-[11px] text-gray-500">Candidate、CoreTrace 与 Effect 的统一投影</p></div>
      <span class="rounded bg-white px-2 py-1 text-xs font-bold text-violet-700">{{ rows.length }} 项</span>
    </header>
    <div ref="scroller" class="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 pb-4">
      <article
        v-for="(step, index) in rows"
        :key="step.id"
        :data-effect-child="step.isEffect ? 'true' : undefined"
        class="rounded-lg bg-white p-3 dark:bg-[#29292b]"
        :class="step.isEffect ? 'ml-5 border-l-2 border-amber-300' : ''"
      >
        <div class="flex items-start gap-2">
          <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-gray-100 text-[10px] font-extrabold">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5"><span class="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold">{{ actionLabel[step.label] || step.label }}</span><span class="rounded px-1.5 py-0.5 text-[10px] font-bold" :class="statusClass[step.status]">{{ statusLabel[step.status] }}</span></div>
            <h3 class="mt-1 text-sm font-extrabold">{{ step.title }}</h3>
            <p v-if="step.description" class="mt-1 text-xs text-gray-500">{{ step.description }}</p>
            <p v-if="step.diagnostic" class="mt-1 text-xs text-rose-700">{{ step.diagnostic }}</p>
            <p v-if="step.isEffect && step.parentId" class="mt-1 text-[10px] text-amber-700">属于动作 {{ step.parentId }}，不计为额外 CoreTrace</p>
          </div>
        </div>
      </article>
      <div v-if="!rows.length" class="rounded-lg bg-white p-8 text-center text-sm text-gray-400">{{ emptyMessage }}</div>
      <div v-if="isRecording" class="py-2 text-center text-xs font-semibold text-violet-700">检测新操作中…</div>
    </div>
  </section>
</template>
