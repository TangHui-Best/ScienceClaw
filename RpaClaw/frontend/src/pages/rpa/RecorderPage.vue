<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { createSession } from '@/api/agent';
import SandboxPreview from '@/components/SandboxPreview.vue';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';
import {
  dispatchRpaAgentManualInput,
  getRpaAgentProjection,
  runRpaAgentInstruction,
  startRpaAgentSession,
  stopRpaAgentSession,
  type BrowserRuntimeScope,
  type RpaAgentManualInputPayload,
} from '@/api/rpaAgent';
import { projectRpaAgentCreationSteps } from '@/utils/rpaAgentCreationProjection';
import { saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const browserSessionRef = ref(String(route.query.browserSessionRef || '').trim());
const sessionId = ref('');
const mainScope = ref<BrowserRuntimeScope | null>(null);
const steps = ref<ReturnType<typeof projectRpaAgentCreationSteps>>([]);
const instruction = ref('');
const agentRunning = ref(false);
const stopping = ref(false);
const error = ref('');
let pollTimer: ReturnType<typeof setInterval> | null = null;
let disposed = false;
let projectionInFlight = false;

const refreshProjection = async () => {
  if (!sessionId.value || disposed || projectionInFlight) return;
  projectionInFlight = true;
  try {
    const response = await getRpaAgentProjection(sessionId.value);
    if (!disposed) {
      steps.value = projectRpaAgentCreationSteps(response.steps);
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
    if (!browserSessionRef.value) {
      const host = await createSession({ mode: 'browser' });
      if (disposed) return;
      browserSessionRef.value = host.session_id;
    }
    const response = await startRpaAgentSession(browserSessionRef.value);
    if (disposed) return;
    sessionId.value = response.session_id;
    mainScope.value = response.main_scope;
    await refreshProjection();
    if (disposed) return;
    pollTimer = setInterval(() => { void refreshProjection(); }, 1200);
  } catch {
    if (!disposed) error.value = '新版 RPA Agent 会话启动失败。';
  }
};

const runInstruction = async () => {
  const text = instruction.value.trim();
  if (!sessionId.value || !text || agentRunning.value) return;
  agentRunning.value = true;
  error.value = '';
  try {
    await runRpaAgentInstruction(sessionId.value, text);
    instruction.value = '';
    await refreshProjection();
  } catch {
    error.value = '自然语言操作执行失败。';
  } finally {
    agentRunning.value = false;
  }
};

const stopRecording = async () => {
  if (!sessionId.value || stopping.value || agentRunning.value) return;
  stopping.value = true;
  try {
    const response = await stopRpaAgentSession(sessionId.value);
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    saveCreationSnapshot({
      sessionId: sessionId.value,
      browserSessionRef: browserSessionRef.value,
      configurationDraft: response.configuration_draft,
      bindingLocations: response.configuration_options.binding_locations,
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
    <header class="flex items-center justify-between border-b bg-white px-5 py-3 dark:border-white/10 dark:bg-[#232325]">
      <div>
        <h1 class="text-lg font-extrabold">{{ t('RPA Agent Recorder') }}</h1>
        <p class="text-xs text-gray-500">直接操作浏览器，复杂步骤交给自然语言。</p>
      </div>
      <button data-testid="stop-recording" type="button" class="rounded-lg bg-rose-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50" :disabled="!sessionId || stopping || agentRunning" @click="stopRecording">
        {{ stopping ? '停止中…' : t('Stop recording') }}
      </button>
    </header>
    <p v-if="error" role="alert" class="bg-rose-50 px-5 py-2 text-sm text-rose-700">{{ error }}</p>
    <div class="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)_320px] gap-3 p-3">
      <aside data-testid="recorder-left" class="min-h-0 overflow-hidden rounded-xl bg-white dark:bg-[#232325]">
        <RpaStepTimeline :steps="steps" title="实时步骤" mode="record" :is-recording="Boolean(sessionId)" :auto-scroll="true" />
      </aside>
      <section data-testid="recorder-center" class="min-h-0 overflow-hidden rounded-xl bg-black">
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
        <h2 class="font-extrabold">{{ t('Natural language operation') }}</h2>
        <p class="mt-1 text-xs text-gray-500">对话期间暂停人工事件提升，浏览器事实观察保持运行。</p>
        <textarea v-model="instruction" name="agent-instruction" class="mt-4 min-h-32 rounded-lg border p-3 text-sm" placeholder="例如：提取目标采购订单字段" :disabled="agentRunning || !sessionId" />
        <button data-testid="run-agent" type="button" class="mt-3 rounded-lg bg-violet-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-50" :disabled="agentRunning || !instruction.trim() || !sessionId" @click="runInstruction">
          {{ agentRunning ? '执行中…' : '执行指令' }}
        </button>
        <div v-if="mainScope" class="mt-auto rounded-lg bg-gray-50 p-2 text-[11px] text-gray-500">浏览器上下文已接入</div>
      </aside>
    </div>
  </main>
</template>
