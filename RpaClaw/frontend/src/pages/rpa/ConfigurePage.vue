<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Braces, Database, KeyRound, Settings, Tag } from 'lucide-vue-next';
import { compileRpaAgentSkill, configureRpaAgentSkill } from '@/api/rpaAgent';
import RpaFlowGuide from '@/components/rpa/RpaFlowGuide.vue';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';
import {
  promoteBindingLocation,
  renamePromotedBindingRef,
  setDraftInputDefault,
  loadCreationSnapshot,
  saveCreationSnapshot,
  type SkillConfigurationDraft,
} from '@/utils/rpaAgentSkillConfiguration';

const route = useRoute();
const router = useRouter();
const sessionId = computed(() => String(route.query.sessionId || ''));
const snapshot = loadCreationSnapshot(sessionId.value);
const creationSnapshot = ref(snapshot);
const draft = ref<SkillConfigurationDraft | null>(snapshot?.configurationDraft ? structuredClone(snapshot.configurationDraft) : null);
const compiling = ref(false);
const error = ref('');
const locations = computed(() => snapshot?.bindingLocations || []);
const steps = computed(() => snapshot?.creationSteps || []);
const diagnostics = computed(() => steps.value.filter((step) => step.status === 'rejected'));
const configurationState = ref<'configured' | 'compiled' | undefined>(snapshot?.configurationState ?? (snapshot?.artifactHash ? 'compiled' : undefined));
const invalidRenameKeys = ref<Set<string>>(new Set());
const hasInvalidRename = computed(() => invalidRenameKeys.value.size > 0);
const isLocked = computed(() => Boolean(configurationState.value));

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

const promoteBinding = (locationValue: { trace_id: string; binding_name: string }, toKind: 'skill_input' | 'secret') => {
  if (!draft.value) return;
  draft.value = promoteBindingLocation(draft.value, locationValue, toKind);
};

const renameInputRef = (oldRef: string, event: Event) => {
  if (!draft.value) return;
  const input = event.target as HTMLInputElement;
  try {
    draft.value = renamePromotedBindingRef(draft.value, 'skill_input', oldRef, input.value);
    markRenameValidity(`input:${oldRef}`, true); error.value = '';
  } catch (exception) {
    input.value = oldRef; markRenameValidity(`input:${oldRef}`, false);
    error.value = exception instanceof Error && exception.message === 'configuration.ref_duplicate' ? '参数引用不能重复。' : '参数引用不能为空。';
  }
};

const renameSecretRef = (oldRef: string, event: Event) => {
  if (!draft.value) return;
  const input = event.target as HTMLInputElement;
  try {
    draft.value = renamePromotedBindingRef(draft.value, 'secret', oldRef, input.value);
    markRenameValidity(`secret:${oldRef}`, true); error.value = '';
  } catch (exception) {
    input.value = oldRef; markRenameValidity(`secret:${oldRef}`, false);
    error.value = exception instanceof Error && exception.message === 'configuration.ref_duplicate' ? 'Secret 引用不能重复。' : 'Secret 引用不能为空。';
  }
};

const changeInputType = (refName: string, type: 'string' | 'number' | 'boolean') => {
  if (!draft.value) return;
  draft.value = { ...draft.value, inputs: draft.value.inputs.map((item) => item.ref === refName ? { ref: item.ref, title: item.title, required: item.required, value_type: type } : item) };
};
const toggleDefault = (refName: string, enabled: boolean) => {
  if (!draft.value) return;
  const input = draft.value.inputs.find((item) => item.ref === refName); if (!input) return;
  const initial = input.value_type === 'number' ? 0 : input.value_type === 'boolean' ? false : '';
  draft.value = setDraftInputDefault(draft.value, refName, enabled, initial);
};
const updateDefault = (refName: string, value: unknown) => {
  if (draft.value) draft.value = setDraftInputDefault(draft.value, refName, true, value);
};

const continueToTest = async () => {
  try {
    await router.push({ path: '/rpa/test', query: { sessionId: sessionId.value } });
    error.value = '';
  } catch {
    error.value = '产物已生成，请重试进入测试页。';
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
      } catch {
        error.value = '配置保存失败，请修正后重试。'; return;
      }
    }
    if (configurationState.value === 'configured') {
      try {
        const artifact = await compileRpaAgentSkill(sessionId.value);
        configurationState.value = 'compiled';
        persistSnapshot({ configurationDraft: draft.value, configurationState: 'compiled', artifactHash: artifact.artifact_hash, artifactFiles: artifact.artifact_files, testPassed: false, savedRef: undefined });
      } catch {
        error.value = '编译失败，配置已保存，可直接重试编译。'; return;
      }
    }
    await continueToTest();
  } finally { compiling.value = false; }
};

const compileLabel = computed(() => compiling.value ? '处理中…' : configurationState.value === 'compiled' ? '进入测试' : configurationState.value === 'configured' ? '重试编译' : '开始测试');
</script>

<template>
  <div class="min-h-screen bg-[#f5f6f7] text-gray-900 dark:bg-[#161618] dark:text-gray-100">
    <RpaFlowGuide
      data-testid="configure-flow-guide"
      class="sticky top-0 z-30"
      current-step="configure"
      :session-id="sessionId"
      :recorded-step-count="steps.length"
      :diagnostic-count="diagnostics.length"
      :skill-name="draft?.skill.name || ''"
      :primary-label="compileLabel"
      :primary-disabled="!draft || compiling || hasInvalidRename"
      @home="router.push('/chat')"
      @skills="router.push('/chat/skills')"
      @go-record="router.push('/rpa/recorder')"
      @go-test="configureAndCompile"
      @primary-action="configureAndCompile"
    />

    <main class="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <p v-if="!draft" role="alert" class="rounded-2xl border border-rose-200 bg-white px-6 py-5 text-sm text-rose-600 shadow-sm dark:bg-[#272728]">配置快照不存在或会话不匹配，请返回录制工作台。</p>

      <form v-else class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]" @submit.prevent="configureAndCompile">
        <section data-testid="configure-steps" class="space-y-4">
          <header class="flex flex-wrap items-center justify-between gap-3">
            <div><h1 class="text-xl font-extrabold tracking-tight">录制步骤</h1><p class="mt-1 text-sm text-gray-500">复核录制过程，点击步骤可查看状态与诊断信息。</p></div>
            <span class="rounded-full bg-white px-4 py-1.5 text-xs font-bold text-[#831bd7] shadow-sm ring-1 ring-[#831bd7]/10 dark:bg-[#272728]">共 {{ steps.length }} 步</span>
          </header>
          <section v-if="diagnostics.length" class="rounded-2xl border border-rose-200 bg-rose-50/80 p-4 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-200"><p class="font-bold">{{ diagnostics.length }} 个步骤需要关注</p><p class="mt-1 text-xs opacity-85">失败或未结算步骤不会进入最终 Skill，请返回录制页重试后再配置。</p></section>
          <RpaStepTimeline class="min-h-[620px] overflow-hidden rounded-2xl" :steps="steps" mode="configure" :show-header="false" empty-message="当前没有可配置的录制步骤。" />
        </section>

        <aside data-testid="configure-skill-panel" class="space-y-4 xl:sticky xl:top-24 xl:self-start">
          <fieldset :disabled="isLocked" class="space-y-4 disabled:opacity-70">
            <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]">
              <div class="flex items-center gap-3"><span class="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#f4eaff] text-[#831bd7]"><Settings :size="18" /></span><div><h2 class="text-base font-extrabold">技能信息</h2><p class="text-[11px] text-gray-500">让使用者一眼理解这个 Skill 的用途</p></div></div>
              <div class="mt-4 space-y-4">
                <label class="block text-xs font-semibold text-gray-500">技能名称<input v-model="draft.skill.name" name="skill-name" class="mt-1.5 w-full rounded-2xl border border-gray-200 bg-[#fafafa] px-3 py-2.5 text-sm font-normal text-gray-900 outline-none focus:border-[#831bd7] dark:border-gray-700 dark:bg-[#383739] dark:text-gray-100" /></label>
                <label class="block text-xs font-semibold text-gray-500">描述<textarea v-model="draft.skill.description" rows="3" class="mt-1.5 w-full resize-none rounded-2xl border border-gray-200 bg-[#fafafa] px-3 py-2.5 text-sm font-normal text-gray-900 outline-none focus:border-[#831bd7] dark:border-gray-700 dark:bg-[#383739] dark:text-gray-100" /></label>
              </div>
            </section>

            <section class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]">
              <div class="flex items-start gap-3"><span class="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#f4eaff] text-[#831bd7]"><Tag :size="18" /></span><div><h2 class="text-base font-extrabold">可配置参数</h2><p class="text-[11px] text-gray-500">把录制值提升为运行时输入或 Secret</p></div></div>
              <div v-if="locations.length" class="mt-4 space-y-3">
                <article v-for="location in locations" :key="`${location.trace_id}:${location.binding_name}`" class="rounded-2xl border border-gray-200 bg-[#fafafa] p-3 dark:border-gray-700 dark:bg-[#383739]">
                  <div class="flex items-center justify-between gap-2"><div class="min-w-0"><p class="truncate text-sm font-semibold">{{ location.binding_name }}</p><p class="mt-0.5 text-[10px] text-gray-400">{{ location.sensitive ? '检测为敏感输入' : '录制时输入值' }}</p></div><span class="rounded-full px-2 py-0.5 text-[10px] font-bold" :class="location.sensitive ? 'bg-fuchsia-100 text-fuchsia-700' : 'bg-slate-100 text-slate-600'">{{ location.sensitive ? '敏感' : '普通' }}</span></div>
                  <div class="mt-3 grid grid-cols-2 gap-2"><button data-testid="promote-binding" type="button" class="rounded-xl bg-[#831bd7] px-2 py-2 text-[11px] font-bold text-white" @click="promoteBinding(location, 'skill_input')">设为输入参数</button><button data-testid="promote-secret" type="button" class="rounded-xl border border-[#831bd7]/30 px-2 py-2 text-[11px] font-bold text-[#831bd7]" @click="promoteBinding(location, 'secret')">设为 Secret</button></div>
                </article>
              </div>
              <div v-else class="mt-4 rounded-2xl border border-dashed border-gray-200 px-4 py-6 text-center text-sm text-gray-400 dark:border-gray-700">当前没有可参数化的录制值。</div>

              <div v-for="input in draft.inputs" :key="input.ref" class="mt-3 grid grid-cols-2 gap-2 rounded-2xl border border-violet-100 bg-violet-50/50 p-3 text-sm dark:border-violet-950 dark:bg-violet-950/20">
                <input :value="input.ref" aria-label="Input ref" class="rounded-xl border border-gray-200 bg-white p-2" @change="renameInputRef(input.ref, $event)" />
                <input v-model="input.title" aria-label="Input title" class="rounded-xl border border-gray-200 bg-white p-2" />
                <label class="flex items-center gap-2 text-xs"><input v-model="input.required" type="checkbox" />必填</label>
                <select :value="input.value_type" class="rounded-xl border border-gray-200 bg-white p-2 text-xs" @change="changeInputType(input.ref, ($event.target as HTMLSelectElement).value as 'string' | 'number' | 'boolean')"><option value="string">文本</option><option value="number">数字</option><option value="boolean">是/否</option></select>
                <label class="flex items-center gap-2 text-xs"><input type="checkbox" :checked="Object.prototype.hasOwnProperty.call(input, 'default')" @change="toggleDefault(input.ref, ($event.target as HTMLInputElement).checked)" />使用默认值</label>
                <select v-if="input.value_type === 'boolean' && Object.prototype.hasOwnProperty.call(input, 'default')" :value="String(input.default)" class="rounded-xl border border-gray-200 bg-white p-2" @change="updateDefault(input.ref, ($event.target as HTMLSelectElement).value)"><option value="false">否</option><option value="true">是</option></select>
                <input v-else-if="Object.prototype.hasOwnProperty.call(input, 'default')" :type="input.value_type === 'number' ? 'number' : 'text'" :value="String(input.default ?? '')" class="rounded-xl border border-gray-200 bg-white p-2" @input="updateDefault(input.ref, ($event.target as HTMLInputElement).value)" />
              </div>
            </section>

            <section v-if="draft.secrets.length" class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]">
              <div class="mb-3 flex items-center gap-2"><KeyRound :size="17" class="text-[#831bd7]" /><h2 class="text-sm font-extrabold">Secret 声明</h2></div>
              <div v-for="item in draft.secrets" :key="`secret:${item.ref}`" class="grid grid-cols-2 gap-2 rounded-2xl bg-[#fafafa] p-3 text-sm dark:bg-[#383739]"><input :value="item.ref" class="rounded-xl border p-2" aria-label="Secret ref" @change="renameSecretRef(item.ref, $event)" /><input v-model="item.title" class="rounded-xl border p-2" /><label class="col-span-2 text-xs"><input v-model="item.required" type="checkbox" /> 必填，仅在测试页输入明文</label></div>
            </section>

            <section v-if="draft.outputs.length" class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]">
              <div class="mb-3 flex items-center gap-2"><Braces :size="17" class="text-[#831bd7]" /><h2 class="text-sm font-extrabold">输出结果</h2></div>
              <div v-for="item in draft.outputs" :key="`output:${item.name}`" class="grid grid-cols-2 gap-2 rounded-2xl bg-[#fafafa] p-3 dark:bg-[#383739]"><input v-model="item.name" class="rounded-xl border p-2 text-sm" /><input v-model="item.title" class="rounded-xl border p-2 text-sm" /><input v-model="item.variable_ref" class="col-span-2 rounded-xl border p-2 text-sm" /><select v-model="item.value_type" class="col-span-2 rounded-xl border p-2 text-sm"><option>string</option><option>number</option><option>boolean</option><option>json</option></select></div>
            </section>

            <section v-if="draft.asset_inputs.length || draft.asset_outputs.length" class="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-[#272728]">
              <div class="mb-3 flex items-center gap-2"><Database :size="17" class="text-[#831bd7]" /><h2 class="text-sm font-extrabold">DataAsset</h2></div>
              <div v-for="item in draft.asset_inputs" :key="`asset-input:${item.ref}`" class="mb-2 grid grid-cols-2 gap-2 rounded-2xl bg-[#fafafa] p-3"><input v-model="item.ref" class="rounded-xl border p-2 text-sm" /><input v-model="item.title" class="rounded-xl border p-2 text-sm" /><label class="col-span-2 text-xs"><input v-model="item.required" type="checkbox" /> 必填输入文件</label></div>
              <div v-for="item in draft.asset_outputs" :key="`asset-output:${item.name}`" class="grid grid-cols-2 gap-2 rounded-2xl bg-[#fafafa] p-3"><input v-model="item.name" class="rounded-xl border p-2 text-sm" /><input v-model="item.title" class="rounded-xl border p-2 text-sm" /><input v-model="item.asset_ref" class="col-span-2 rounded-xl border p-2 text-sm" /></div>
            </section>
          </fieldset>

          <p v-if="error" role="alert" class="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-950/30 dark:text-rose-200">{{ error }}</p>
          <button data-testid="compile-skill" type="submit" class="w-full rounded-2xl bg-gradient-to-r from-[#841cd8] to-[#ac0189] px-5 py-3 text-sm font-extrabold text-white shadow-sm shadow-[#841cd8]/20 disabled:opacity-50" :disabled="compiling || hasInvalidRename">{{ compileLabel }}</button>
        </aside>
      </form>
    </main>
  </div>
</template>
