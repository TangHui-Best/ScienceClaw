<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
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
let pollTimer: ReturnType<typeof setInterval> | null = null;
let disposed = false;
let projectionInFlight = false;
const agentRunning = computed(() => steps.value.some((step) =>
  step.kind === 'ai_instruction' && ['queued', 'running'].includes(step.executionStatus),
));
const aiConversation = computed(() => steps.value.filter((step) => step.kind === 'ai_instruction'));

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

const stopRecording = async () => {
  if (!sessionId.value || stopping.value || agentRunning.value) return;
  stopping.value = true;
  try {
    const response = await stopRpaAgentSession(sessionId.value);
    const stoppedProjection = await getRpaAgentProjection(sessionId.value);
    steps.value = projectRpaAgentCreationSteps(stoppedProjection.items);
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
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
});
</script>

<template>
  <main class="flex h-[calc(100vh-64px)] min-h-0 flex-col bg-gray-100 dark:bg-[#171718]">
    <header class="flex items-center justify-between border-b border-[var(--border-main)] bg-[var(--background-white-main)] px-5 py-3">
      <div>
        <h1 class="text-lg font-extrabold">{{ t('RPA Agent Recorder') }}</h1>
        <p class="text-xs text-gray-500">直接操作浏览器，复杂步骤交给自然语言。</p>
      </div>
      <button data-testid="stop-recording" type="button" class="rounded-lg bg-rose-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50" :disabled="!sessionId || stopping || agentRunning" @click="stopRecording">
        {{ stopping ? '停止中…' : t('Stop recording') }}
      </button>
    </header>
    <p v-if="error" role="alert" class="bg-rose-50 px-5 py-2 text-sm text-rose-700">{{ error }}</p>
    <RpaFlowGuide current-step="record" />
    <div class="grid min-h-0 flex-1 grid-cols-[292px_minmax(0,1fr)_336px] gap-3 p-3 pt-2">
      <aside data-testid="recorder-left" class="min-h-0 overflow-hidden rounded-xl bg-white dark:bg-[#232325]">
        <RpaStepTimeline :steps="steps" title="实时步骤" mode="record" :is-recording="Boolean(sessionId)" :auto-scroll="true" />
      </aside>
      <section data-testid="recorder-center" class="flex min-h-0 flex-col overflow-hidden rounded-xl bg-black">
        <form v-if="browserSessionRef" class="flex shrink-0 items-center gap-2 border-b border-gray-200 bg-white px-3 py-2 dark:border-gray-700 dark:bg-[#232325]" @submit.prevent="navigateRecordingBrowser">
          <label for="recording-url" class="sr-only">录制浏览器地址</label>
          <input id="recording-url" v-model="navigationUrl" name="recording-url" type="url" required placeholder="https://github.com/trending" class="min-w-0 flex-1 rounded-lg border border-[var(--border-main)] bg-[var(--background-gray-main)] px-3 py-2 text-xs text-[var(--text-primary)]" :disabled="navigating || agentRunning || !sessionId" />
          <button data-testid="navigate-recording-browser" type="submit" class="rounded-lg bg-slate-800 px-3 py-2 text-xs font-bold text-white disabled:opacity-50 dark:bg-slate-600" :disabled="navigating || agentRunning || !sessionId || !navigationUrl.trim()">
            {{ navigating ? '打开中…' : '打开' }}
          </button>
        </form>
        <SandboxPreview
          v-if="browserSessionRef"
          mode="browser"
          :is-live="true"
          :session-id="browserSessionRef"
          variant="inline"
          :manual-input-dispatcher="dispatchManualInput"
          :manual-input-disabled="agentRunning || !sessionId"
        />
      </section>
      <aside data-testid="recorder-right" class="flex min-h-0 flex-col rounded-xl bg-white p-4 dark:bg-[#232325]">
        <div class="flex items-start justify-between gap-3">
          <div><h2 class="font-extrabold">{{ t('Natural language operation') }}</h2><p class="mt-1 text-xs text-gray-500">原始指令会立即进入时间线，执行证据随后补充。</p></div>
          <span v-if="agentRunning" class="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700">Agent 运行中</span>
        </div>
        <div class="mt-4 min-h-0 flex-1 space-y-2 overflow-y-auto" aria-live="polite">
          <div v-if="!aiConversation.length" class="rounded-lg bg-[var(--background-gray-main)] p-3 text-xs text-[var(--text-tertiary)]">可用自然语言处理跨页面、判断和提取任务。</div>
          <article v-for="step in aiConversation" :key="step.id" class="rounded-lg border border-[var(--border-main)] p-3">
            <p class="text-sm text-[var(--text-primary)]">{{ step.title }}</p>
            <p class="mt-1 text-[11px] text-[var(--text-tertiary)]">{{ step.validation.details }}<span v-if="step.observations.length"> · {{ step.observations.length }} 条动作证据</span></p>
          </article>
        </div>
        <label class="mt-3 text-[11px] font-semibold text-[var(--text-secondary)]" for="agent-model">运行模型</label>
        <select id="agent-model" v-model="selectedModelId" class="mt-1 rounded-lg border border-[var(--border-main)] bg-[var(--background-white-main)] px-3 py-2 text-xs" :disabled="submittingInstruction || !models.length">
          <option value="">使用默认模型</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.name || model.model_name }}</option>
        </select>
        <textarea v-model="instruction" name="agent-instruction" class="mt-3 min-h-24 rounded-lg border border-[var(--border-main)] bg-[var(--background-white-main)] p-3 text-sm" placeholder="例如：打开和 skill 最相关的项目" :disabled="submittingInstruction || !sessionId" @keydown.ctrl.enter.prevent="runInstruction" />
        <button data-testid="run-agent" type="button" class="mt-3 rounded-lg bg-[var(--Button-primary-brand)] px-4 py-2 text-sm font-bold text-white disabled:opacity-50" :disabled="submittingInstruction || !instruction.trim() || !sessionId" @click="runInstruction">
          {{ submittingInstruction ? '提交中…' : '执行指令' }}
        </button>
        <div v-if="generation" class="mt-2 text-center text-[10px] text-[var(--text-disable)]">独立录制环境已就绪</div>
      </aside>
    </div>
  </main>
</template>
