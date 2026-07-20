<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { Bot, CheckCircle, Globe, Loader2, Radio, Send, Wand2 } from 'lucide-vue-next';
import { listModels, type ModelConfig } from '@/api/models';
import SandboxPreview from '@/components/SandboxPreview.vue';
import RpaFlowGuide from '@/components/rpa/RpaFlowGuide.vue';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';
import {
  dispatchRpaAgentManualInput,
  getRpaAgentProjection,
  runRpaAgentInstruction,
  startRpaAgentSession,
  stopRpaAgentSession,
  type RpaAgentManualInputPayload,
} from '@/api/rpaAgent';
import { projectRpaAgentCreationSteps } from '@/utils/rpaAgentCreationProjection';
import { saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';

const router = useRouter();
const route = useRoute();
const { t } = useI18n();
const browserSessionRef = ref('');
const sessionId = ref('');
const generation = ref('');
const steps = ref<ReturnType<typeof projectRpaAgentCreationSteps>>([]);
const instruction = ref('');
const navigationUrl = ref('');
const navigating = ref(false);
const submittingInstruction = ref(false);
const models = ref<ModelConfig[]>([]);
const selectedModelId = ref('');
const stopping = ref(false);
const error = ref('');
const elapsedSeconds = ref(0);
let pollTimer: ReturnType<typeof setInterval> | null = null;
let clockTimer: ReturnType<typeof setInterval> | null = null;
let disposed = false;
let projectionInFlight = false;
const agentRunning = computed(() => steps.value.some((step) =>
  step.kind === 'ai_instruction' && ['queued', 'running'].includes(step.executionStatus),
));
const aiConversation = computed(() => steps.value.filter((step) => step.kind === 'ai_instruction'));
const selectedModel = computed(() => models.value.find((model) => model.id === selectedModelId.value));
const recordingTime = computed(() => `${Math.floor(elapsedSeconds.value / 60).toString().padStart(2, '0')}:${(elapsedSeconds.value % 60).toString().padStart(2, '0')}`);

const refreshProjection = async () => {
  if (!sessionId.value || disposed || projectionInFlight) return;
  projectionInFlight = true;
  try {
    const response = await getRpaAgentProjection(sessionId.value);
    if (!disposed) {
      steps.value = projectRpaAgentCreationSteps(response.items);
      error.value = '';
    }
  } catch {
    if (!disposed) error.value = '步骤投影刷新失败。';
  } finally {
    projectionInFlight = false;
  }
};

const dispatchManualInput = async (payload: RpaAgentManualInputPayload) => {
  if (!sessionId.value || agentRunning.value || disposed) {
    throw new Error('rpa_agent.manual_input_unavailable');
  }
  await dispatchRpaAgentManualInput(sessionId.value, payload);
  await refreshProjection();
};

const start = async () => {
  try {
    const prestarted = route.query.sessionId && route.query.browserSessionRef && route.query.generation
      ? {
          session_id: String(route.query.sessionId),
          state: 'recording' as const,
          browser_session_ref: String(route.query.browserSessionRef),
          page_ref: String(route.query.pageRef || 'main'),
          generation: String(route.query.generation),
        }
      : null;
    const [response, availableModels] = await Promise.all([
      prestarted ? Promise.resolve(prestarted) : startRpaAgentSession(),
      listModels().catch(() => [] as ModelConfig[]),
    ]);
    if (disposed) return;
    sessionId.value = response.session_id;
    browserSessionRef.value = response.browser_session_ref;
    generation.value = response.generation;
    models.value = availableModels;
    selectedModelId.value = availableModels[0]?.id || '';
    await refreshProjection();
    if (disposed) return;
    pollTimer = setInterval(() => { void refreshProjection(); }, 1200);
    clockTimer = setInterval(() => { elapsedSeconds.value += 1; }, 1000);
  } catch {
    if (!disposed) error.value = '新版 RPA Agent 会话启动失败。';
  }
};

const runInstruction = async () => {
  const text = instruction.value.trim();
  if (!sessionId.value || !text || submittingInstruction.value) return;
  submittingInstruction.value = true;
  error.value = '';
  try {
    await runRpaAgentInstruction(sessionId.value, text, {
      model_id: selectedModelId.value || undefined,
      business_terms: [], required_variable_refs: [], allowed_inputs: {},
      allowed_secret_names: [], allowed_data_assets: {}, page_aliases: {},
    });
    instruction.value = '';
    await refreshProjection();
  } catch {
    error.value = '指令提交失败，尚未创建 AI 步骤。';
  } finally {
    submittingInstruction.value = false;
  }
};

const navigateRecordingBrowser = async () => {
  const url = navigationUrl.value.trim();
  if (!sessionId.value || !url || navigating.value || agentRunning.value) return;
  navigating.value = true;
  error.value = '';
  try {
    await dispatchManualInput({
      input_id: `input_nav_${Date.now().toString(36)}`,
      kind: 'navigate',
      text: url,
    });
  } catch {
    error.value = '导航失败，未写入手工步骤。';
  } finally {
    navigating.value = false;
  }
};

const handleComposerKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    void runInstruction();
  }
};

const stopRecording = async () => {
  if (!sessionId.value || stopping.value || agentRunning.value) return;
  stopping.value = true;
  try {
    const response = await stopRpaAgentSession(sessionId.value);
    const stoppedProjection = await getRpaAgentProjection(sessionId.value);
    steps.value = projectRpaAgentCreationSteps(stoppedProjection.items);
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
    saveCreationSnapshot({
      sessionId: sessionId.value,
      browserSessionRef: browserSessionRef.value,
      configurationDraft: response.configuration_draft,
      bindingLocations: response.configuration_options.binding_locations.map((item) => ({ ...item })),
      recordingSteps: steps.value.map((step) => ({
        id: step.id,
        ordinal: step.ordinal,
        kind: step.kind,
        title: step.title,
        replayStatus: step.replayStatus,
        compileMode: step.compileMode,
      })),
    });
    await router.push({ path: '/rpa/configure', query: { sessionId: sessionId.value } });
  } catch {
    error.value = '停止录制失败，尚未进入配置。';
  } finally {
    stopping.value = false;
  }
};

onMounted(() => { void start(); });
onBeforeUnmount(() => {
  disposed = true;
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
});
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-[#f5f6f7] text-gray-900 dark:bg-[#161618] dark:text-gray-100">
    <RpaFlowGuide data-testid="rpa-flow-guide" current-step="record" :session-id="sessionId" :recorded-step-count="steps.length" :is-recording="Boolean(sessionId)" :recording-time="recordingTime" primary-label="完成录制" :primary-disabled="!sessionId || stopping || agentRunning" @go-configure="stopRecording" @primary-action="stopRecording" />
    <p v-if="error" role="alert" class="shrink-0 bg-rose-50 px-5 py-2 text-sm text-rose-700">{{ error }}</p>
    <div class="flex min-h-0 flex-1 overflow-hidden">
      <aside data-testid="recorder-left" class="flex w-80 shrink-0 overflow-hidden bg-[#eff1f2] dark:bg-[#212122]"><RpaStepTimeline :steps="steps" title="实时步骤" mode="record" :is-recording="Boolean(sessionId)" :auto-scroll="true" empty-message="在浏览器中操作后，步骤会自动出现在这里。" /></aside>
      <main data-testid="recorder-center" class="flex min-w-0 flex-1 flex-col px-5 py-4">
        <section data-testid="recorder-browser-workspace" class="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-gray-800 bg-[#1e1e1e] shadow-2xl">
          <div class="flex h-9 shrink-0 items-end gap-2 bg-[#cfd3d8] px-3 dark:bg-[#2a2a2b]"><div class="h-7 min-w-36 rounded-t-xl border border-b-0 border-gray-300 bg-[#f5f6f7] px-3 pt-1.5 text-[11px] dark:bg-[#161618]">{{ browserSessionRef ? 'RPA Agent 录制浏览器' : '正在连接浏览器…' }}</div></div>
          <div class="flex h-9 shrink-0 items-center gap-2 bg-[#dadddf] px-3 dark:bg-[#383839]">
            <div class="flex gap-1.5"><i class="h-2.5 w-2.5 rounded-full bg-red-400"></i><i class="h-2.5 w-2.5 rounded-full bg-yellow-400"></i><i class="h-2.5 w-2.5 rounded-full bg-green-400"></i></div>
            <form class="mx-3 flex h-6 flex-1 items-center rounded-md bg-white px-2 shadow-inner dark:bg-[#272728]" @submit.prevent="navigateRecordingBrowser"><Globe :size="12" class="text-gray-400" /><input v-model="navigationUrl" name="recording-url" data-testid="recorder-address" type="url" class="ml-2 flex-1 bg-transparent text-[11px] outline-none" :disabled="navigating || agentRunning || !sessionId" placeholder="输入网址并按回车打开" /><Loader2 v-if="navigating" :size="12" class="animate-spin text-[#831bd7]" /><button data-testid="navigate-recording-browser" type="submit" class="sr-only" :disabled="navigating || agentRunning || !sessionId || !navigationUrl.trim()">打开</button></form>
          </div>
          <div class="recorder-preview min-h-0 flex-1 bg-black"><SandboxPreview v-if="browserSessionRef" mode="browser" :is-live="true" :session-id="browserSessionRef" variant="inline" :manual-input-dispatcher="dispatchManualInput" :manual-input-disabled="agentRunning || !sessionId" /></div>
          <div class="pointer-events-none absolute bottom-7 left-1/2 hidden -translate-x-1/2 items-center gap-2 rounded-full bg-black/55 px-3 py-1.5 sm:flex"><Radio :size="13" class="animate-pulse text-red-400" /><span class="text-[10px] font-bold text-white">实时 CDP 串流</span></div>
        </section>
      </main>
      <aside data-testid="recorder-right" class="flex w-80 shrink-0 flex-col border-l border-gray-200 bg-[#eff1f2] dark:border-gray-700 dark:bg-[#212122]">
        <header class="flex items-center gap-3 border-b border-gray-100 p-5"><span class="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#831bd7] to-[#ac0089] text-white"><Wand2 :size="20" /></span><div><h2 class="text-sm font-bold">AI 录制助手</h2><p class="text-[10px] font-bold" :class="agentRunning ? 'text-orange-500' : 'text-[#831bd7]'">{{ agentRunning ? '正在处理你的操作…' : '按描述录制操作' }}</p></div></header>
        <div data-testid="assistant-conversation" class="min-h-0 flex-1 space-y-4 overflow-y-auto p-5" aria-live="polite">
          <div v-if="!aiConversation.length" class="mt-8 text-center text-xs leading-5 text-gray-400">在浏览器中直接操作，或用自然语言描述复杂步骤。所有步骤会立即出现在左侧。</div>
          <div v-for="step in aiConversation" :key="step.id" class="space-y-2"><div class="ml-auto max-w-[88%] rounded-2xl rounded-tr-none bg-[#831bd7] px-3 py-2.5 text-xs text-white">{{ step.title }}</div><div class="rounded-xl bg-white p-3 text-xs shadow-sm dark:bg-[#272728]"><div class="flex items-center gap-2 font-bold"><Loader2 v-if="['queued','running'].includes(step.executionStatus)" :size="14" class="animate-spin text-[#831bd7]" /><CheckCircle v-else-if="step.executionStatus === 'succeeded'" :size="14" class="text-emerald-500" /><Bot v-else :size="14" class="text-rose-500" /><span>任务处理进度</span></div><p class="mt-2 text-gray-500">{{ step.validation.details }}<span v-if="step.observations.length">，已观察 {{ step.observations.length }} 个动作</span></p></div></div>
        </div>
        <div class="p-4"><div class="rounded-2xl bg-white p-2 shadow-lg dark:bg-[#272728]"><textarea v-model="instruction" name="agent-instruction" rows="2" class="h-16 w-full resize-none bg-transparent px-2 pt-1 text-xs outline-none" :disabled="submittingInstruction || !sessionId" placeholder="描述录制目标或操作…" @keydown="handleComposerKeydown"></textarea><div class="flex items-center gap-2"><select id="agent-model" v-model="selectedModelId" data-testid="assistant-model" class="min-w-0 flex-1 rounded-lg bg-[#f2f4f6] px-2 py-1.5 text-[10px]" :disabled="submittingInstruction || !models.length"><option value="">使用系统默认模型</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.name || model.model_name }}</option></select><button data-testid="run-agent" type="button" class="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-[#831bd7] to-[#ac0089] text-white disabled:opacity-50" :disabled="submittingInstruction || !instruction.trim() || !sessionId" @click="runInstruction"><Send :size="15" /></button></div></div><button data-testid="stop-recording" type="button" class="sr-only" :disabled="!sessionId || stopping || agentRunning" @click="stopRecording">{{ t('Stop recording') }}</button><p v-if="selectedModel" class="mt-2 truncate px-1 text-[9px] text-gray-400">当前模型：{{ selectedModel.model_name }}</p><p v-if="generation" class="mt-1 px-1 text-[9px] text-gray-400">独立录制环境已就绪</p></div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.recorder-preview :deep(.sandbox-preview) { height: 100%; min-height: 0 !important; border: 0; border-radius: 0; }
.recorder-preview :deep(.sandbox-preview > div:first-child) { display: none; }
.recorder-preview :deep(.section-content-enter) { height: 100% !important; min-height: 0 !important; max-height: none !important; }
@media (prefers-reduced-motion: reduce) { .animate-pulse, .animate-spin { animation: none; } }
</style>
