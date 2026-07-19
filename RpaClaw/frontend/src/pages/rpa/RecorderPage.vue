<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Bot, CheckCircle, Globe, Loader2, Radio, Send, Wand2 } from 'lucide-vue-next';
import { createSession } from '@/api/agent';
import { listModels, type ModelConfig } from '@/api/models';
import SandboxPreview from '@/components/SandboxPreview.vue';
import RpaFlowGuide from '@/components/rpa/RpaFlowGuide.vue';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';
import {
  discardRpaAgentSession,
  dispatchRpaAgentManualInput,
  getRpaAgentProjection,
  runRpaAgentInstruction,
  startRpaAgentSession,
  stopRpaAgentSession,
  type BrowserRuntimeScope,
  type RpaAgentInstructionContext,
  type RpaAgentManualInputPayload,
} from '@/api/rpaAgent';
import { projectRpaAgentCreationSteps } from '@/utils/rpaAgentCreationProjection';
import { saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';

type ConversationMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  status?: 'running' | 'done' | 'error';
  actionCount?: number;
  time: string;
};

const EMPTY_CONTEXT: RpaAgentInstructionContext = {
  business_terms: [],
  required_variable_refs: [],
  allowed_inputs: {},
  allowed_secret_names: [],
  allowed_data_assets: {},
  page_aliases: {},
};

const route = useRoute();
const router = useRouter();
const browserSessionRef = ref(String(route.query.browserSessionRef || '').trim());
const sessionId = ref('');
const mainScope = ref<BrowserRuntimeScope | null>(null);
const steps = ref<ReturnType<typeof projectRpaAgentCreationSteps>>([]);
const instruction = ref('');
const addressInput = ref('');
const agentRunning = ref(false);
const stopping = ref(false);
const error = ref('');
const models = ref<ModelConfig[]>([]);
const selectedModelId = ref('');
const messages = ref<ConversationMessage[]>([]);
const chatScrollRef = ref<HTMLElement | null>(null);
const elapsedSeconds = ref(0);
let pollTimer: ReturnType<typeof setInterval> | null = null;
let clockTimer: ReturnType<typeof setInterval> | null = null;
let disposed = false;
let projectionInFlight = false;
let recordingFinished = false;
let discarding = false;

const recordingTime = computed(() => {
  const minutes = Math.floor(elapsedSeconds.value / 60).toString().padStart(2, '0');
  const seconds = (elapsedSeconds.value % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
});

const selectedModel = computed(() => models.value.find((model) => model.id === selectedModelId.value) || null);
const acceptedStepCount = computed(() => steps.value.filter((step) => step.status === 'accepted').length);
const diagnosticCount = computed(() => steps.value.filter((step) => step.status === 'rejected').length);

const nowLabel = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
const scrollChat = async () => {
  await nextTick();
  const target = chatScrollRef.value?.lastElementChild as HTMLElement | null | undefined;
  if (typeof target?.scrollIntoView === 'function') target.scrollIntoView({ block: 'nearest' });
};

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
    if (!disposed) error.value = '录制步骤刷新失败，请检查后端连接。';
  } finally {
    projectionInFlight = false;
  }
};

const dispatchManualInput = async (payload: RpaAgentManualInputPayload) => {
  if (!sessionId.value || agentRunning.value || disposed) throw new Error('rpa_agent.manual_input_unavailable');
  await dispatchRpaAgentManualInput(sessionId.value, payload);
  await refreshProjection();
};

const loadModels = async () => {
  try {
    models.value = (await listModels()).filter((model) => model.is_active !== false);
    const preferred = models.value.find((model) => model.model_name === 'qwen3.7-plus-2026-05-26')
      || models.value.find((model) => model.is_system)
      || models.value[0];
    selectedModelId.value = preferred?.id || '';
  } catch {
    models.value = [];
    selectedModelId.value = '';
  }
};

const start = async () => {
  try {
    await loadModels();
    if (!browserSessionRef.value) {
      const host = await createSession({ mode: 'browser' });
      if (disposed) return;
      browserSessionRef.value = host.session_id;
    }
    const response = await startRpaAgentSession(browserSessionRef.value);
    if (disposed) {
      await discardRpaAgentSession(response.session_id).catch(() => undefined);
      return;
    }
    sessionId.value = response.session_id;
    mainScope.value = response.main_scope;
    await refreshProjection();
    if (disposed) return;
    pollTimer = setInterval(() => { void refreshProjection(); }, 1200);
    clockTimer = setInterval(() => { elapsedSeconds.value += 1; }, 1000);
  } catch {
    if (!disposed) error.value = 'RPA Agent 录制会话启动失败，请确认本地浏览器与后端服务已启动。';
  }
};

const discardActiveRecording = async () => {
  const activeSessionId = sessionId.value;
  if (!activeSessionId || recordingFinished || discarding) return;
  discarding = true;
  try {
    await discardRpaAgentSession(activeSessionId);
    recordingFinished = true;
    sessionId.value = '';
    mainScope.value = null;
  } finally {
    discarding = false;
  }
};

const leaveRecorder = async (path: string) => {
  try {
    await discardActiveRecording();
  } catch {
    // A fresh backend session still receives an isolated BrowserContext even
    // if best-effort exit cleanup fails.  Do not trap the user on this page.
  }
  await router.push(path);
};

const executeInstruction = async (text: string) => {
  if (!sessionId.value || !text || agentRunning.value) return;
  agentRunning.value = true;
  error.value = '';
  const runId = `message_${Date.now()}`;
  messages.value.push({ id: `${runId}_user`, role: 'user', text, time: nowLabel() });
  messages.value.push({ id: runId, role: 'assistant', text: 'Agent 正在规划并执行浏览器操作…', status: 'running', time: nowLabel() });
  instruction.value = '';
  await scrollChat();
  try {
    const result = await runRpaAgentInstruction(sessionId.value, text, EMPTY_CONTEXT, selectedModelId.value || undefined);
    const actionCount = Number(result.replayable_action_count || 0);
    const agentResult = typeof result.agent_result === 'string' ? result.agent_result.trim() : '';
    const message = messages.value.find((item) => item.id === runId);
    if (message) {
      message.status = 'done';
      message.actionCount = actionCount;
      message.text = agentResult
        ? `${agentResult}\n\n已记录 ${actionCount} 个可回放步骤。`
        : `任务完成，本次记录 ${actionCount} 个可回放步骤。`;
    }
    await refreshProjection();
  } catch {
    const message = messages.value.find((item) => item.id === runId);
    if (message) {
      message.status = 'error';
      message.text = '任务执行失败，浏览器未记录不完整步骤。请调整描述后重试。';
    }
    error.value = '自然语言操作执行失败，请检查模型配置或后端日志。';
  } finally {
    agentRunning.value = false;
    await scrollChat();
  }
};

const runInstruction = () => executeInstruction(instruction.value.trim());
const submitAddressBar = () => {
  const raw = addressInput.value.trim();
  if (!raw) return;
  const url = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  addressInput.value = url;
  void executeInstruction(`打开网页 ${url}`);
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
  // Freeze the visible projection before the stop request. The polling request
  // may settle while stop is in flight and replace the recording projection.
  const recordedSteps = steps.value.map((step) => ({ ...step }));
  try {
    const response = await stopRpaAgentSession(sessionId.value);
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
    saveCreationSnapshot({
      sessionId: sessionId.value,
      browserSessionRef: browserSessionRef.value,
      creationSteps: response.creation_steps?.length
        ? projectRpaAgentCreationSteps(response.creation_steps)
        : recordedSteps,
      configurationDraft: response.configuration_draft,
      bindingLocations: response.configuration_options.binding_locations,
    });
    recordingFinished = true;
    await router.push({ path: '/rpa/configure', query: { sessionId: sessionId.value } });
  } catch {
    error.value = '停止录制失败，尚未进入配置页。';
  } finally {
    stopping.value = false;
  }
};

onMounted(() => { void start(); });
onBeforeUnmount(() => {
  disposed = true;
  if (pollTimer) clearInterval(pollTimer);
  if (clockTimer) clearInterval(clockTimer);
  if (!recordingFinished && sessionId.value) void discardActiveRecording();
});
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-[#f5f6f7] text-gray-900 dark:bg-[#161618] dark:text-gray-100">
    <RpaFlowGuide
      data-testid="rpa-flow-guide"
      current-step="record"
      :session-id="sessionId"
      :recorded-step-count="acceptedStepCount"
      :diagnostic-count="diagnosticCount"
      :is-recording="Boolean(sessionId)"
      :recording-time="recordingTime"
      primary-label="完成录制"
      :primary-disabled="!sessionId || stopping || agentRunning"
      @home="leaveRecorder('/chat')"
      @skills="leaveRecorder('/chat/skills')"
      @go-configure="stopRecording"
      @primary-action="stopRecording"
    />

    <p v-if="error" role="alert" class="shrink-0 bg-rose-50 px-5 py-2 text-sm text-rose-700 dark:bg-rose-950/30 dark:text-rose-200">{{ error }}</p>

    <div class="flex min-h-0 flex-1 overflow-hidden">
      <aside data-testid="recorder-left" class="flex w-80 shrink-0 overflow-hidden bg-[#eff1f2] dark:bg-[#212122]">
        <RpaStepTimeline
          :steps="steps"
          title="实时步骤"
          mode="record"
          :is-recording="Boolean(sessionId)"
          :auto-scroll="true"
          :diagnostics-count="diagnosticCount"
          diagnostics-message="失败步骤不会进入最终 Skill，可调整操作后重试。"
          empty-message="在浏览器中操作后，步骤会自动出现在这里。"
        />
      </aside>

      <main data-testid="recorder-center" class="flex min-w-0 flex-1 flex-col bg-[#f5f6f7] px-5 py-4 dark:bg-[#161618]">
        <section data-testid="recorder-browser-workspace" class="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-gray-800 bg-[#1e1e1e] shadow-2xl dark:border-gray-600">
          <div class="flex h-9 shrink-0 items-end gap-2 overflow-hidden bg-[#cfd3d8] px-3 dark:bg-[#2a2a2b]">
            <div class="h-7 min-w-36 max-w-64 truncate rounded-t-xl border border-b-0 border-gray-300 bg-[#f5f6f7] px-3 pt-1.5 text-[11px] text-gray-700 dark:border-gray-600 dark:bg-[#161618] dark:text-gray-200">
              {{ mainScope ? 'RPA Agent 录制浏览器' : '正在连接浏览器…' }}
            </div>
          </div>
          <div class="flex h-9 shrink-0 items-center gap-2 border-t border-white/40 bg-[#dadddf] px-3 dark:border-white/10 dark:bg-[#383839]">
            <div class="flex gap-1.5"><i class="h-2.5 w-2.5 rounded-full bg-red-400"></i><i class="h-2.5 w-2.5 rounded-full bg-yellow-400"></i><i class="h-2.5 w-2.5 rounded-full bg-green-400"></i></div>
            <form class="mx-3 flex h-6 flex-1 items-center rounded-md bg-white px-2 shadow-inner dark:bg-[#272728]" @submit.prevent="submitAddressBar">
              <Globe :size="12" class="shrink-0 text-gray-400" />
              <input v-model="addressInput" data-testid="recorder-address" class="ml-2 flex-1 bg-transparent text-[11px] text-gray-700 outline-none dark:text-gray-200" :disabled="agentRunning || !sessionId" placeholder="输入网址并按回车打开" />
              <Loader2 v-if="agentRunning" :size="12" class="animate-spin text-[#831bd7]" />
            </form>
          </div>
          <div class="recorder-preview min-h-0 flex-1 bg-black">
            <SandboxPreview
              v-if="browserSessionRef"
              mode="browser"
              :is-live="true"
              :session-id="browserSessionRef"
              variant="inline"
              :manual-input-dispatcher="dispatchManualInput"
              :manual-input-disabled="agentRunning || !sessionId"
            />
          </div>
          <div class="pointer-events-none absolute bottom-7 left-1/2 hidden -translate-x-1/2 items-center gap-2 rounded-full border border-white/20 bg-black/55 px-3 py-1.5 sm:flex">
            <Radio :size="13" class="animate-pulse text-red-400" /><span class="text-[10px] font-bold tracking-wider text-white">实时 CDP 串流</span>
          </div>
        </section>
      </main>

      <aside data-testid="recorder-right" class="flex w-80 shrink-0 flex-col border-l border-gray-200 bg-[#eff1f2] shadow-[-10px_0_40px_-10px_rgba(0,0,0,0.03)] dark:border-gray-700 dark:bg-[#212122]">
        <header class="flex items-center gap-3 border-b border-gray-100 p-5 dark:border-gray-800">
          <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#831bd7] to-[#ac0089] text-white shadow-lg shadow-purple-200/60 dark:shadow-none"><Wand2 :size="20" /></span>
          <div><h2 class="text-sm font-bold">AI 录制助手</h2><p class="text-[10px] font-bold" :class="agentRunning ? 'text-orange-500' : 'text-[#831bd7]'">{{ agentRunning ? '正在处理你的操作…' : '按描述录制操作' }}</p></div>
        </header>

        <div ref="chatScrollRef" data-testid="assistant-conversation" class="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <div v-if="!messages.length" class="mt-8 text-center text-xs leading-5 text-gray-400">在浏览器中直接操作，或用自然语言描述复杂步骤。所有已确认步骤会出现在左侧。</div>
          <div v-for="message in messages" :key="message.id" class="flex flex-col gap-1" :class="message.role === 'user' ? 'items-end' : 'items-start'">
            <div v-if="message.role === 'user'" class="max-w-[88%] rounded-2xl rounded-tr-none bg-[#831bd7] px-3 py-2.5 text-xs leading-relaxed text-white shadow-sm">{{ message.text }}</div>
            <div v-else class="w-full rounded-xl bg-white p-3 text-xs shadow-[0_14px_30px_rgba(25,28,30,0.06)] dark:bg-[#272728]">
              <div class="flex items-center gap-2 font-bold"><Loader2 v-if="message.status === 'running'" :size="14" class="animate-spin text-[#831bd7]" /><CheckCircle v-else-if="message.status === 'done'" :size="14" class="text-emerald-500" /><Bot v-else :size="14" class="text-rose-500" /><span>任务处理进度</span></div>
              <p class="mt-2 leading-relaxed" :class="message.status === 'error' ? 'text-rose-600' : 'text-gray-600 dark:text-gray-300'">{{ message.text }}</p>
            </div>
            <span class="px-1 text-[9px] text-gray-400">{{ message.time }}</span>
          </div>
        </div>

        <div class="p-4">
          <div class="rounded-2xl bg-white p-2 shadow-[0_16px_36px_rgba(25,28,30,0.08)] ring-1 ring-black/[0.04] dark:bg-[#272728] dark:ring-white/10">
            <textarea v-model="instruction" name="agent-instruction" rows="2" class="h-16 w-full resize-none bg-transparent px-2 pt-1 text-xs leading-relaxed outline-none placeholder:text-gray-400" :disabled="agentRunning || !sessionId" :placeholder="agentRunning ? 'Agent 运行中…' : '描述录制目标或操作…'" @keydown="handleComposerKeydown"></textarea>
            <div class="flex items-center justify-between gap-2">
              <select v-model="selectedModelId" data-testid="assistant-model" class="min-w-0 flex-1 truncate rounded-lg bg-[#f2f4f6] px-2 py-1.5 text-[10px] font-semibold outline-none dark:bg-white/10" :disabled="agentRunning || !models.length">
                <option v-if="!models.length" value="">使用系统默认模型</option>
                <option v-for="model in models" :key="model.id" :value="model.id">{{ model.name || model.model_name }} · {{ model.model_name }}</option>
              </select>
              <button data-testid="run-agent" type="button" class="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#831bd7] to-[#ac0089] text-white shadow-[0_10px_22px_rgba(131,27,215,0.24)] disabled:opacity-50" :disabled="agentRunning || !instruction.trim() || !sessionId" @click="runInstruction"><Send :size="15" /></button>
            </div>
          </div>
          <button data-testid="stop-recording" type="button" class="sr-only" :disabled="!sessionId || stopping || agentRunning" @click="stopRecording">完成录制</button>
          <p v-if="selectedModel" class="mt-2 truncate px-1 text-[9px] text-gray-400">当前模型：{{ selectedModel.model_name }}</p>
        </div>
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
