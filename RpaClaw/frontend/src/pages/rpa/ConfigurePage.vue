<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Braces, Database, KeyRound, Settings, Tag } from 'lucide-vue-next';
import { compileRpaAgentSkill, configureRpaAgentSkill, rerecordRpaAgentSession } from '@/api/rpaAgent';
import RpaFlowGuide from '@/components/rpa/RpaFlowGuide.vue';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';
import type { RpaAgentCreationStepViewModel } from '@/utils/rpaAgentCreationProjection';
import {
  promoteBindingLocation,
  renamePromotedBindingRef,
  setDraftInputDefault,
  loadCreationSnapshot,
  saveCreationSnapshot,
  type SkillConfigurationDraft,
} from '@/utils/rpaAgentSkillConfiguration';

const route = useRoute(); const router = useRouter();
const sessionId = computed(() => String(route.query.sessionId || ''));
const snapshot = loadCreationSnapshot(sessionId.value);
const creationSnapshot = ref(snapshot);
const draft = ref<SkillConfigurationDraft | null>(snapshot?.configurationDraft ? structuredClone(snapshot.configurationDraft) : null);
const compiling = ref(false); const error = ref('');
const locations = computed(() => snapshot?.bindingLocations || []);
const configurationState = ref<'configured' | 'compiled' | undefined>(snapshot?.configurationState ?? (snapshot?.artifactHash ? 'compiled' : undefined));
const invalidRenameKeys = ref<Set<string>>(new Set());
const hasInvalidRename = computed(() => invalidRenameKeys.value.size > 0);
const recordingSteps = computed(() => snapshot?.recordingSteps || []);
const isLocked = computed(() => Boolean(configurationState.value));
const compileLabel = computed(() => compiling.value ? '处理中…' : configurationState.value === 'compiled' ? '进入测试' : configurationState.value === 'configured' ? '重试编译' : '开始测试');
const configureSteps = computed<RpaAgentCreationStepViewModel[]>(() => recordingSteps.value.map((step) => ({
  id: step.id, ordinal: step.ordinal, kind: step.kind, title: step.title, description: step.title,
  label: step.kind === 'manual' ? '手工' : 'AI', action: step.kind === 'manual' ? 'manual' : 'agent',
  captureStatus: 'captured', executionStatus: 'succeeded', replayStatus: step.replayStatus,
  compileMode: step.compileMode, observations: [], isEffect: false, is_action: true,
  validation: { status: step.replayStatus, details: step.compileMode ? `将以 ${step.compileMode === 'playwright' ? 'Playwright' : 'Agent'} 回放` : '需要补充回退指令或重新录制' },
})));

const formatApiError = (exception: unknown) => {
  const value = exception as { message?: unknown; details?: { detail?: unknown; message?: unknown } };
  const detail = value?.details?.detail ?? value?.message;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const issue = item as { loc?: unknown[]; msg?: string };
      const location = Array.isArray(issue.loc) ? issue.loc.join('.') : 'request';
      return `${location}: ${issue.msg || 'invalid value'}`;
    }).join('；');
  }
  if (detail && typeof detail === 'object') {
    const nested = detail as { code?: unknown; message?: unknown; detail?: unknown };
    const nestedValue = nested.message ?? nested.detail ?? nested.code;
    if (typeof nestedValue === 'string' && nestedValue) return nestedValue;
    return JSON.stringify(detail);
  }
  return typeof detail === 'string' && detail ? detail : '请修正后重试';
};

const addOutput = () => {
  if (!draft.value) return;
  let suffix = draft.value.outputs.length + 1;
  while (draft.value.outputs.some((item) => item.name === `output_${suffix}`)) suffix += 1;
  draft.value.outputs.push({
    name: `output_${suffix}`,
    title: `输出 ${suffix}`,
    variable_ref: `result.output_${suffix}`,
    value_type: 'string',
  });
};

const toggleAgentOutput = (stepId: string, outputName: string, enabled: boolean) => {
  if (!draft.value?.agent_steps?.[stepId]) return;
  const step = draft.value.agent_steps[stepId];
  const refs = new Set(step.output_refs);
  if (enabled) refs.add(outputName); else refs.delete(outputName);
  draft.value.agent_steps[stepId] = { ...step, output_refs: [...refs] };
};

const setManualFallback = (stepId: string, instruction: string) => {
  if (!draft.value) return;
  const fallbacks = { ...(draft.value.manual_fallbacks || {}) };
  if (instruction.trim()) {
    fallbacks[stepId] = {
      trace_id: stepId,
      instruction: instruction.trim(),
      scope_hint: { page_ref: 'main', frame_path: [] },
    };
  } else delete fallbacks[stepId];
  draft.value.manual_fallbacks = fallbacks;
};

const persistSnapshot = (updates: Partial<NonNullable<typeof snapshot>>) => {
  if (!creationSnapshot.value) return;
  const next = { ...creationSnapshot.value, ...updates };
  saveCreationSnapshot(next);
  creationSnapshot.value = next;
};

const markRenameValidity = (key: string, valid: boolean) => {
  const next = new Set(invalidRenameKeys.value);
  if (valid) next.delete(key); else next.add(key);
  invalidRenameKeys.value = next;
};

const promoteBinding = (locationValue: Record<string, unknown>, toKind: 'skill_input' | 'secret') => {
  if (!draft.value) return;
  const location = locationValue as { trace_id: string; binding_name: string };
  draft.value = promoteBindingLocation(draft.value, location, toKind);
};

const renameInputRef = (oldRef: string, event: Event) => {
  if (!draft.value) return;
  const input = event.target as HTMLInputElement;
  try {
    draft.value = renamePromotedBindingRef(draft.value, 'skill_input', oldRef, input.value);
    markRenameValidity(`input:${oldRef}`, true);
    error.value = '';
  } catch (exception) {
    input.value = oldRef;
    markRenameValidity(`input:${oldRef}`, false);
    error.value = exception instanceof Error && exception.message === 'configuration.ref_duplicate'
      ? 'Ref 不能重复。'
      : 'Ref 不能为空。';
  }
};
const renameSecretRef = (oldRef: string, event: Event) => {
  if (!draft.value) return;
  const input = event.target as HTMLInputElement;
  try {
    draft.value = renamePromotedBindingRef(draft.value, 'secret', oldRef, input.value);
    markRenameValidity(`secret:${oldRef}`, true);
    error.value = '';
  } catch (exception) {
    input.value = oldRef;
    markRenameValidity(`secret:${oldRef}`, false);
    error.value = exception instanceof Error && exception.message === 'configuration.ref_duplicate'
      ? 'Ref 不能重复。'
      : 'Ref 不能为空。';
  }
};
const changeInputType = (ref: string, type: 'string' | 'number' | 'boolean') => {
  if (!draft.value) return;
  draft.value = { ...draft.value, inputs: draft.value.inputs.map((item) => item.ref === ref ? { ref: item.ref, title: item.title, required: item.required, value_type: type } : item) };
};
const toggleDefault = (ref: string, enabled: boolean) => {
  if (!draft.value) return;
  const input = draft.value.inputs.find((item) => item.ref === ref);
  if (!input) return;
  const initial = input.value_type === 'number' ? 0 : input.value_type === 'boolean' ? false : '';
  draft.value = setDraftInputDefault(draft.value, ref, enabled, initial);
};
const updateDefault = (ref: string, value: unknown) => {
  if (draft.value) draft.value = setDraftInputDefault(draft.value, ref, true, value);
};

const continueToTest = async () => {
  try {
    await router.push({ path: '/rpa/test', query: { sessionId: sessionId.value } });
    error.value = '';
  } catch {
    error.value = '产物已生成，请重试进入测试页。';
  }
};

const rerecord = async () => {
  if (!sessionId.value || compiling.value) return;
  compiling.value = true;
  error.value = '';
  try {
    const next = await rerecordRpaAgentSession(sessionId.value);
    await router.push({
      path: '/rpa/recorder',
      query: {
        sessionId: next.session_id,
        browserSessionRef: next.browser_session_ref,
        pageRef: next.page_ref,
        generation: next.generation,
      },
    });
  } catch (exception) {
    error.value = `重新录制失败：${formatApiError(exception)}`;
  } finally {
    compiling.value = false;
  }
};

const configureAndCompile = async () => {
  if (!snapshot || !draft.value || compiling.value || hasInvalidRename.value) return;
  compiling.value = true; error.value = '';
  try {
    if (!configurationState.value) {
      try {
        await configureRpaAgentSkill(sessionId.value, draft.value);
        configurationState.value = 'configured';
        persistSnapshot({ configurationDraft: draft.value, configurationState: 'configured' });
      } catch (exception) {
        error.value = `配置保存失败：${formatApiError(exception)}`;
        return;
      }
    }
    if (configurationState.value === 'configured') {
      try {
        const artifact = await compileRpaAgentSkill(sessionId.value);
        configurationState.value = 'compiled';
        persistSnapshot({
          configurationDraft: draft.value,
          configurationState: 'compiled',
          artifactHash: artifact.artifact_hash,
          artifactFiles: artifact.artifact_files,
          testPassed: false,
          savedRef: undefined,
        });
      } catch {
        error.value = '编译失败，配置已保存，可直接重试编译。';
        return;
      }
    }
    await continueToTest();
  } finally { compiling.value = false; }
};
</script>

<template>
  <div class="min-h-screen bg-[#f5f6f7] text-gray-900 dark:bg-[#161618] dark:text-gray-100">
    <RpaFlowGuide data-testid="configure-flow-guide" class="sticky top-0 z-30" current-step="configure" :session-id="sessionId" :recorded-step-count="recordingSteps.length" :skill-name="draft?.skill.name || ''" :primary-label="compileLabel" :primary-disabled="!draft || compiling || hasInvalidRename" @go-record="rerecord" @go-test="configureAndCompile" @primary-action="configureAndCompile" />
    <main class="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <p v-if="!draft" role="alert" class="rounded-2xl border border-rose-200 bg-white px-6 py-5 text-sm text-rose-600">配置快照不存在或会话不匹配，请返回录制工作台。</p>
      <form v-else class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]" @submit.prevent="configureAndCompile">
        <section data-testid="configure-steps" class="space-y-4"><header class="flex items-center justify-between"><div><h1 class="text-xl font-extrabold">录制步骤</h1><p class="mt-1 text-sm text-gray-500">点击步骤查看执行与编译依据；主流程顺序保持不变。</p></div><span class="rounded-full bg-white px-4 py-1.5 text-xs font-bold text-[#831bd7] shadow-sm">共 {{ recordingSteps.length }} 步</span></header><RpaStepTimeline class="min-h-[620px] overflow-hidden rounded-2xl" :steps="configureSteps" mode="configure" :show-header="false" empty-message="当前没有可配置的录制步骤。" /></section>
        <aside data-testid="configure-skill-panel" class="space-y-4 xl:sticky xl:top-24 xl:self-start">
          <fieldset :disabled="isLocked" class="space-y-4 disabled:opacity-70">
            <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]"><div class="flex items-center gap-3"><span class="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#f4eaff] text-[#831bd7]"><Settings :size="18" /></span><div><h2 class="font-extrabold">技能信息</h2><p class="text-[11px] text-gray-500">名称与用途说明</p></div></div><label class="mt-4 block text-xs font-semibold text-gray-500">技能名称<input v-model="draft.skill.name" name="skill-name" class="mt-1.5 w-full rounded-2xl border bg-[#fafafa] px-3 py-2.5 text-sm font-normal" /></label><label class="mt-3 block text-xs font-semibold text-gray-500">描述<textarea v-model="draft.skill.description" rows="3" class="mt-1.5 w-full resize-none rounded-2xl border bg-[#fafafa] px-3 py-2.5 text-sm font-normal" /></label></section>
            <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]"><div class="flex items-center gap-2"><Tag :size="17" class="text-[#831bd7]" /><h2 class="font-extrabold">步骤编译与参数</h2></div><article v-for="step in recordingSteps" :key="step.id" class="mt-3 rounded-2xl bg-[#fafafa] p-3"><div class="flex items-start justify-between gap-2"><p class="text-xs font-bold">{{ step.ordinal }}. {{ step.title }}</p><span class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold" :class="step.compileMode === 'playwright' ? 'bg-emerald-50 text-emerald-700' : step.compileMode === 'agent' ? 'bg-purple-50 text-purple-700' : 'bg-amber-50 text-amber-700'">{{ step.compileMode === 'playwright' ? 'Playwright' : step.compileMode === 'agent' ? 'Agent' : '需确认' }}</span></div><div v-if="step.kind === 'ai_instruction' && draft.agent_steps?.[step.id]" class="mt-2"><label v-for="output in draft.outputs" :key="`${step.id}:${output.name}`" class="mr-3 inline-flex items-center gap-1 text-[11px]"><input type="checkbox" :checked="draft.agent_steps[step.id].output_refs.includes(output.name)" @change="toggleAgentOutput(step.id, output.name, ($event.target as HTMLInputElement).checked)" />输出 {{ output.name }}</label></div><label v-if="step.kind === 'manual' && step.replayStatus !== 'deterministic_ready'" class="mt-2 block text-[11px] font-bold">回退指令<textarea class="mt-1 w-full rounded-xl border p-2 font-normal" @change="setManualFallback(step.id, ($event.target as HTMLTextAreaElement).value)" /></label></article>
              <article v-for="location in locations" :key="`${location.trace_id}:${location.binding_name}`" class="mt-3 rounded-2xl border bg-[#fafafa] p-3"><p class="truncate text-xs font-semibold">{{ location.binding_name }}</p><div class="mt-2 grid grid-cols-2 gap-2"><button data-testid="promote-binding" type="button" class="rounded-xl bg-[#831bd7] px-2 py-2 text-[11px] font-bold text-white" @click="promoteBinding(location, 'skill_input')">设为输入参数</button><button data-testid="promote-secret" type="button" class="rounded-xl border border-[#831bd7]/30 px-2 py-2 text-[11px] font-bold text-[#831bd7]" @click="promoteBinding(location, 'secret')">设为 Secret</button></div></article>
              <div v-for="input in draft.inputs" :key="input.ref" class="mt-3 grid grid-cols-2 gap-2 rounded-2xl bg-violet-50/50 p-3 text-xs"><input :value="input.ref" aria-label="Input ref" class="rounded-xl border p-2" @change="renameInputRef(input.ref, $event)" /><input v-model="input.title" aria-label="Input title" class="rounded-xl border p-2" /><label><input v-model="input.required" type="checkbox" /> 必填</label><select :value="input.value_type" class="rounded-xl border p-2" @change="changeInputType(input.ref, ($event.target as HTMLSelectElement).value as 'string' | 'number' | 'boolean')"><option value="string">文本</option><option value="number">数字</option><option value="boolean">是/否</option></select><label><input type="checkbox" :checked="Object.prototype.hasOwnProperty.call(input, 'default')" @change="toggleDefault(input.ref, ($event.target as HTMLInputElement).checked)" /> 默认值</label><input v-if="Object.prototype.hasOwnProperty.call(input, 'default')" :type="input.value_type === 'number' ? 'number' : 'text'" :value="String(input.default ?? '')" class="rounded-xl border p-2" @input="updateDefault(input.ref, ($event.target as HTMLInputElement).value)" /></div>
            </section>
            <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]"><div class="flex items-center justify-between"><div class="flex items-center gap-2"><Braces :size="17" class="text-[#831bd7]" /><h2 class="font-extrabold">输出与资源</h2></div><button type="button" class="rounded-xl border px-3 py-1.5 text-xs font-bold text-[#831bd7]" @click="addOutput">新增输出</button></div><div v-for="item in draft.outputs" :key="`output:${item.name}`" class="mt-3 grid grid-cols-2 gap-2 rounded-2xl bg-[#fafafa] p-3"><input v-model="item.name" aria-label="输出名称" class="rounded-xl border p-2 text-xs" /><input v-model="item.title" aria-label="输出标题" class="rounded-xl border p-2 text-xs" /><input v-model="item.variable_ref" aria-label="输出变量引用" class="col-span-2 rounded-xl border p-2 text-xs" /><select v-model="item.value_type" aria-label="输出类型" class="col-span-2 rounded-xl border p-2 text-xs"><option>string</option><option>number</option><option>boolean</option><option>json</option></select></div><div v-if="draft.secrets.length" class="mt-4 flex items-center gap-2 text-xs font-bold"><KeyRound :size="15" />Secret 声明</div><div v-for="item in draft.secrets" :key="item.ref" class="mt-2 grid grid-cols-2 gap-2"><input :value="item.ref" class="rounded-xl border p-2 text-xs" @change="renameSecretRef(item.ref, $event)" /><input v-model="item.title" class="rounded-xl border p-2 text-xs" /></div><div v-if="draft.asset_inputs.length || draft.asset_outputs.length" class="mt-4 flex items-center gap-2 text-xs font-bold"><Database :size="15" />DataAsset</div><div v-for="item in draft.asset_inputs" :key="item.ref" class="mt-2 grid grid-cols-2 gap-2"><input v-model="item.ref" class="rounded-xl border p-2 text-xs" /><input v-model="item.title" class="rounded-xl border p-2 text-xs" /></div></section>
          </fieldset>
          <p v-if="error" role="alert" class="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</p><button data-testid="compile-skill" type="submit" class="w-full rounded-2xl bg-gradient-to-r from-[#841cd8] to-[#ac0189] px-5 py-3 text-sm font-extrabold text-white disabled:opacity-50" :disabled="compiling || hasInvalidRename">{{ compileLabel }}</button>
        </aside>
      </form>
    </main>
  </div>
</template>
