<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { compileRpaAgentSkill, configureRpaAgentSkill, rerecordRpaAgentSession } from '@/api/rpaAgent';
import RpaFlowGuide from '@/components/rpa/RpaFlowGuide.vue';
import {
  promoteBindingLocation,
  renamePromotedBindingRef,
  setDraftInputDefault,
  loadCreationSnapshot,
  saveCreationSnapshot,
  type SkillConfigurationDraft,
} from '@/utils/rpaAgentSkillConfiguration';

const route = useRoute(); const router = useRouter();
const { t } = useI18n();
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
    <RpaFlowGuide class="sticky top-0 z-30" current-step="configure" :session-id="sessionId" :recorded-step-count="recordingSteps.length" @go-record="rerecord" />
  <main class="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
    <header><h1 class="text-2xl font-extrabold">{{ t('Post-recording configuration') }}</h1><p class="mt-1 text-sm text-gray-500">配置名称、输入、Secret、输出与 DataAsset，然后确定性编译。</p></header>
    <p v-if="!draft" role="alert" class="mt-6 rounded-lg bg-rose-50 p-4 text-rose-700">配置快照不存在或 session id 不匹配，请返回录制工作台。</p>
    <form v-else class="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]" @submit.prevent="configureAndCompile">
      <fieldset :disabled="Boolean(configurationState)" class="space-y-5">
      <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]">
        <div class="flex items-center justify-between gap-3"><div><h2 class="font-extrabold">顶层步骤与编译方式</h2><p class="mt-1 text-xs text-gray-500">每个用户步骤只选择一种执行模式。</p></div><span class="rounded-full bg-violet-50 px-3 py-1 text-xs font-bold text-violet-700">{{ recordingSteps.length }} 步</span></div>
        <article v-for="step in recordingSteps" :key="step.id" class="mt-3 rounded-2xl border border-gray-200 bg-[#fafafa] p-4 dark:border-gray-700 dark:bg-[#383739]">
          <div class="flex items-start justify-between gap-3"><div><p class="text-xs font-bold text-gray-500">{{ String(step.ordinal).padStart(2, '0') }} · {{ step.kind === 'manual' ? '手工' : 'AI' }}</p><h3 class="mt-1 text-sm font-extrabold">{{ step.title }}</h3></div><span class="rounded-full px-2.5 py-1 text-[11px] font-bold" :class="step.compileMode === 'playwright' ? 'bg-emerald-50 text-emerald-700' : step.compileMode === 'agent' ? 'bg-purple-50 text-purple-700' : 'bg-amber-50 text-amber-700'">{{ step.compileMode === 'playwright' ? 'Playwright' : step.compileMode === 'agent' ? '运行时 AI' : '需确认' }}</span></div>
          <div v-if="step.kind === 'ai_instruction' && draft.agent_steps?.[step.id]" class="mt-3">
            <p class="text-[11px] font-bold text-gray-500">该步骤输出</p>
            <label v-for="output in draft.outputs" :key="`${step.id}:${output.name}`" class="mr-3 mt-2 inline-flex items-center gap-1.5 text-xs"><input type="checkbox" :checked="draft.agent_steps[step.id].output_refs.includes(output.name)" @change="toggleAgentOutput(step.id, output.name, ($event.target as HTMLInputElement).checked)" />{{ output.name }}</label>
            <p v-if="!draft.outputs.length" class="mt-2 text-xs text-amber-700">请先在“声明输入输出”中新增输出契约。</p>
          </div>
          <label v-if="step.kind === 'manual' && step.replayStatus !== 'deterministic_ready'" class="mt-3 block text-xs font-bold">回退指令<textarea class="mt-1 w-full rounded-xl border p-2 font-normal" placeholder="描述运行时 AI 应完成的原始意图" @change="setManualFallback(step.id, ($event.target as HTMLTextAreaElement).value)" /></label>
        </article>
      </section>
      <section class="grid gap-4 rounded-xl bg-white p-5 shadow-sm dark:bg-[#252527] md:grid-cols-2">
        <label class="text-sm font-bold">SKILL 名称<input v-model="draft.skill.name" name="skill-name" class="mt-2 w-full rounded-lg border p-2 font-normal" /></label>
        <label class="text-sm font-bold">说明<textarea v-model="draft.skill.description" class="mt-2 w-full rounded-lg border p-2 font-normal" /></label>
      </section>
      <section class="rounded-xl bg-white p-5 shadow-sm dark:bg-[#252527]">
        <h2 class="font-extrabold">参数与精确绑定</h2>
        <p class="mt-1 text-xs text-gray-500">每项提升以 trace_id + binding_name 唯一定位。</p>
        <div v-for="location in locations" :key="`${location.trace_id}:${location.binding_name}`" class="mt-3 flex items-center justify-between rounded-lg bg-gray-50 p-3 text-sm">
          <code>{{ location.trace_id }} · {{ location.binding_name }}</code>
          <div class="flex gap-2">
            <button data-testid="promote-binding" type="button" class="rounded bg-violet-700 px-3 py-1.5 font-bold text-white" @click="promoteBinding(location, 'skill_input')">提升为 Input</button>
            <button data-testid="promote-secret" type="button" class="rounded border border-violet-700 px-3 py-1.5 font-bold text-violet-700" @click="promoteBinding(location, 'secret')">提升为 Secret</button>
          </div>
        </div>
        <div v-for="input in draft.inputs" :key="input.ref" class="mt-3 grid grid-cols-2 gap-2 rounded-lg border p-3 text-sm md:grid-cols-4">
          <input :value="input.ref" class="rounded border p-2" aria-label="Input ref" @change="renameInputRef(input.ref, $event)" />
          <input v-model="input.title" class="rounded border p-2" aria-label="Input title" />
          <label class="flex items-center gap-2"><input v-model="input.required" type="checkbox" />required</label>
          <select :value="input.value_type" class="rounded border p-2" @change="changeInputType(input.ref, ($event.target as HTMLSelectElement).value as 'string' | 'number' | 'boolean')"><option value="string">string</option><option value="number">number</option><option value="boolean">boolean</option></select>
          <label class="flex items-center gap-2"><input type="checkbox" :checked="Object.prototype.hasOwnProperty.call(input, 'default')" @change="toggleDefault(input.ref, ($event.target as HTMLInputElement).checked)" />设置默认值</label>
          <select v-if="input.value_type === 'boolean' && Object.prototype.hasOwnProperty.call(input, 'default')" :value="String(input.default)" class="rounded border p-2" @change="updateDefault(input.ref, ($event.target as HTMLSelectElement).value)"><option value="false">false</option><option value="true">true</option></select>
          <input v-else-if="Object.prototype.hasOwnProperty.call(input, 'default')" :type="input.value_type === 'number' ? 'number' : 'text'" :value="String(input.default ?? '')" class="rounded border p-2" @input="updateDefault(input.ref, ($event.target as HTMLInputElement).value)" />
        </div>
      </section>
      <section class="rounded-xl bg-white p-5 shadow-sm dark:bg-[#252527]">
        <div class="flex items-center justify-between"><h2 class="font-extrabold">声明输入输出</h2><button type="button" class="rounded-lg border border-violet-300 px-3 py-1.5 text-xs font-bold text-violet-700" @click="addOutput">新增输出</button></div>
        <p class="mt-1 text-xs text-gray-500">这里只声明 Secret 名称；明文仅在测试页内存输入。</p>
        <div class="mt-3 space-y-3 text-sm">
          <div v-for="item in draft.secrets" :key="`secret:${item.ref}`" class="grid grid-cols-3 gap-2"><input :value="item.ref" class="rounded border p-2" @change="renameSecretRef(item.ref, $event)" /><input v-model="item.title" class="rounded border p-2" /><label><input v-model="item.required" type="checkbox" /> required</label></div>
          <div v-for="item in draft.outputs" :key="`output:${item.name}`" class="grid grid-cols-4 gap-2"><input v-model="item.name" aria-label="输出名称" class="rounded border p-2" /><input v-model="item.title" aria-label="输出标题" class="rounded border p-2" /><input v-model="item.variable_ref" aria-label="输出变量引用" class="rounded border p-2" /><select v-model="item.value_type" aria-label="输出类型" class="rounded border p-2"><option>string</option><option>number</option><option>boolean</option><option>json</option></select></div>
          <div v-for="item in draft.asset_inputs" :key="`asset-input:${item.ref}`" class="grid grid-cols-3 gap-2"><input v-model="item.ref" class="rounded border p-2" /><input v-model="item.title" class="rounded border p-2" /><label><input v-model="item.required" type="checkbox" /> required</label></div>
          <div v-for="item in draft.asset_outputs" :key="`asset-output:${item.name}`" class="grid grid-cols-3 gap-2"><input v-model="item.name" class="rounded border p-2" /><input v-model="item.title" class="rounded border p-2" /><input v-model="item.asset_ref" class="rounded border p-2" /></div>
        </div>
      </section>
      </fieldset>
      <aside class="space-y-4 xl:sticky xl:top-24 xl:self-start"><section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]"><h2 class="font-extrabold">编译确认</h2><p class="mt-2 text-xs leading-5 text-gray-500">先保存契约，再生成唯一四文件产物。配置失败不会破坏上次可运行版本。</p><p v-if="error" role="alert" class="mt-3 text-sm text-rose-700">{{ error }}</p><button data-testid="compile-skill" type="submit" class="mt-4 w-full rounded-xl bg-violet-700 px-5 py-2.5 font-bold text-white disabled:opacity-50" :disabled="compiling || hasInvalidRename">{{ compiling ? '处理中…' : configurationState === 'compiled' ? '进入测试' : configurationState === 'configured' ? '重试编译' : t('Save configuration and compile') }}</button></section></aside>
    </form>
  </main>
  </div>
</template>
