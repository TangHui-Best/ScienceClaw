<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { AlertTriangle, Bot, ChevronDown, ChevronUp, Loader2, Radio, Wand2 } from 'lucide-vue-next';

export interface RpaAgentTimelineViewModel {
  id: string;
  status: 'pending' | 'accepted' | 'rejected' | 'deleted' | 'effect' | 'running' | 'succeeded' | 'failed';
  title: string;
  label: string;
  parentId?: string | null;
  isEffect?: boolean;
  description?: string;
  diagnostic?: string;
  traceId?: string | null;
  validation?: { status: string; details: string };
}

const props = withDefaults(defineProps<{
  steps: RpaAgentTimelineViewModel[];
  title?: string;
  mode?: 'record' | 'configure' | 'test';
  isRecording?: boolean;
  autoScroll?: boolean;
  emptyMessage?: string;
  showHeader?: boolean;
  diagnosticsCount?: number;
  diagnosticsMessage?: string;
}>(), {
  title: '录制步骤', mode: 'record', isRecording: false, autoScroll: false,
  emptyMessage: '当前没有步骤。', showHeader: true, diagnosticsCount: 0, diagnosticsMessage: '',
});

const scrollerRef = ref<HTMLElement | null>(null);
const expandedId = ref<string | null>(null);
const rows = computed(() => props.steps.filter((step) => step.status !== 'deleted'));
const statusLabel: Record<RpaAgentTimelineViewModel['status'], string> = {
  pending: '待结算', accepted: '已确认', rejected: '已拒绝', deleted: '已删除', effect: '结果',
  running: '执行中', succeeded: '已完成', failed: '执行失败',
};
const statusClass: Record<RpaAgentTimelineViewModel['status'], string> = {
  pending: 'bg-violet-50 text-[#831bd7] dark:bg-violet-950/30 dark:text-violet-200',
  accepted: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200',
  rejected: 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-200',
  deleted: 'bg-gray-100 text-gray-500', effect: 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-200',
  running: 'bg-violet-50 text-[#831bd7]', succeeded: 'bg-emerald-50 text-emerald-700', failed: 'bg-rose-50 text-rose-700',
};
const actionLabel: Record<string, string> = {
  click: '点击', fill: '输入', set_checked: '勾选', select_option: '选择', navigate: '导航',
  extract: '获取数据', agent: 'AI 操作', effect: '操作结果', navigation: '页面跳转', new_page: '打开新页', download: '下载',
};

const toggle = (id: string) => { expandedId.value = expandedId.value === id ? null : id; };

watch(() => props.steps.length, async () => {
  if (!props.autoScroll) return;
  await nextTick();
  scrollerRef.value?.lastElementChild?.scrollIntoView({ block: 'nearest' });
});
</script>

<template>
  <section class="flex min-h-0 flex-1 flex-col overflow-hidden bg-[#eff1f2] dark:bg-[#212122]">
    <header v-if="showHeader" class="shrink-0 px-3 pb-2.5 pt-4">
      <div class="flex items-center justify-between gap-3">
        <div class="min-w-0"><h2 class="text-base font-extrabold text-gray-950 dark:text-gray-100">{{ title }}</h2><p class="mt-0.5 truncate text-[11px] font-medium text-gray-500">默认显示业务摘要，展开查看高级信息</p></div>
        <div class="flex shrink-0 items-center gap-2">
          <span v-if="isRecording" class="inline-flex items-center gap-1 rounded-md bg-violet-50 px-2 py-1 text-[10px] font-bold text-[#831bd7] dark:bg-violet-950/30 dark:text-violet-200"><Radio :size="11" class="animate-pulse" />自动跟随</span>
          <span class="rounded-md bg-white px-2 py-1 text-[10px] font-extrabold text-[#831bd7] dark:bg-[#272728]">{{ rows.length }} 步</span>
        </div>
      </div>
      <div v-if="diagnosticsCount" class="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-950/30 dark:text-rose-200"><p class="flex items-center gap-1.5 font-bold"><AlertTriangle :size="13" />{{ diagnosticsCount }} 个步骤待处理</p><p class="mt-1 text-[11px] opacity-85">{{ diagnosticsMessage || '请修复失败步骤后再继续。' }}</p></div>
    </header>

    <div ref="scrollerRef" class="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-1.5 pb-4">
      <article v-for="(step, index) in rows" :key="step.id" :data-effect-child="step.isEffect ? 'true' : undefined" class="group relative overflow-hidden rounded-lg bg-white transition-colors dark:bg-[#272728]" :class="[step.isEffect ? 'ml-5' : '', expandedId === step.id ? 'ring-2 ring-violet-100 dark:ring-violet-950/50' : 'hover:bg-[#fbfbfc] dark:hover:bg-[#303032]']">
        <button type="button" class="block w-full px-2 py-2 text-left" @click="toggle(step.id)">
          <div class="flex min-w-0 items-start gap-1.5 pr-4">
            <span class="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md bg-[#edeef0] text-[9px] font-extrabold text-gray-600 dark:bg-white/10 dark:text-gray-300">{{ String(index + 1).padStart(2, '0') }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex min-w-0 items-center gap-1">
                <span class="shrink-0 rounded bg-[#edeef0] px-1 py-0.5 text-[10px] font-bold leading-3 text-gray-600 dark:bg-white/10 dark:text-gray-300">{{ actionLabel[step.label] || step.label || '操作' }}</span>
                <span v-if="step.label === 'agent'" class="inline-flex items-center gap-0.5 rounded bg-violet-50 px-1 py-0.5 text-[10px] font-bold text-[#831bd7]"><Bot :size="10" />AI</span>
                <span class="rounded px-1 py-0.5 text-[10px] font-bold leading-3" :class="statusClass[step.status]">{{ statusLabel[step.status] }}</span>
              </div>
              <h3 class="mt-1 line-clamp-2 break-words text-[13px] font-extrabold leading-[18px] text-gray-950 dark:text-gray-100">{{ step.title }}</h3>
              <p v-if="step.isEffect" class="mt-0.5 truncate text-[11px] text-gray-500">该结果属于上一步操作，不额外增加录制步骤</p>
              <p v-else-if="step.description && step.description !== step.title" class="mt-0.5 truncate text-[11px] text-gray-500">{{ step.description }}</p>
            </div>
          </div>
        </button>
        <button type="button" class="absolute right-1 top-1.5 flex h-5 w-5 items-center justify-center rounded text-gray-400 hover:bg-[#edeef0] dark:hover:bg-white/10" title="展开高级信息" @click.stop="toggle(step.id)"><ChevronUp v-if="expandedId === step.id" :size="14" /><ChevronDown v-else :size="14" /></button>
        <div v-if="expandedId === step.id" class="space-y-2 bg-[#f7f4fa] px-2.5 pb-2.5 pt-2 dark:bg-[#342f3a]">
          <div class="rounded-lg bg-white p-2.5 text-xs dark:bg-[#272728]"><p class="mb-2 font-bold">高级信息</p><dl class="space-y-2 text-[11px]"><div><dt class="font-bold uppercase text-gray-400">状态</dt><dd class="mt-0.5">{{ statusLabel[step.status] }}</dd></div><div v-if="step.traceId"><dt class="font-bold uppercase text-gray-400">步骤引用</dt><dd class="mt-0.5 break-all font-mono">{{ step.traceId }}</dd></div><div v-if="step.diagnostic || step.validation?.details"><dt class="font-bold uppercase text-gray-400">诊断</dt><dd class="mt-0.5 break-words text-rose-600">{{ step.diagnostic || step.validation?.details }}</dd></div></dl></div>
        </div>
      </article>

      <div v-if="!rows.length" class="flex flex-col items-center justify-center gap-3 rounded-xl bg-white py-10 text-center text-gray-400 dark:bg-[#272728]"><Loader2 v-if="mode === 'test'" :size="20" class="animate-spin text-[#831bd7]" /><Wand2 v-else :size="20" class="text-[#831bd7]" /><p class="px-4 text-xs font-medium">{{ emptyMessage }}</p></div>
      <div v-if="isRecording" class="flex flex-col items-center justify-center gap-2 rounded-xl bg-white/60 py-5 text-center dark:bg-white/5"><Wand2 :size="18" class="animate-pulse text-[#831bd7]" /><p class="text-xs font-semibold text-gray-500">检测新操作中...</p></div>
    </div>
  </section>
</template>

<style scoped>
@media (prefers-reduced-motion: reduce) { .animate-pulse, .animate-spin { animation: none; } }
</style>
