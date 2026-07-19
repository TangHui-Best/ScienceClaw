<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { compileRpaAgentSkill, configureRpaAgentSkill } from '@/api/rpaAgent';
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
        error.value = '配置保存失败，请修正后重试。';
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
  <main class="mx-auto max-w-5xl p-6">
    <header><h1 class="text-2xl font-extrabold">{{ t('Post-recording configuration') }}</h1><p class="mt-1 text-sm text-gray-500">配置名称、输入、Secret、输出与 DataAsset，然后确定性编译。</p></header>
    <p v-if="!draft" role="alert" class="mt-6 rounded-lg bg-rose-50 p-4 text-rose-700">配置快照不存在或 session id 不匹配，请返回录制工作台。</p>
    <form v-else class="mt-6 space-y-5" @submit.prevent="configureAndCompile">
      <fieldset :disabled="Boolean(configurationState)" class="contents">
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
        <h2 class="font-extrabold">声明输入输出</h2>
        <p class="mt-1 text-xs text-gray-500">这里只声明 Secret 名称；明文仅在测试页内存输入。</p>
        <div class="mt-3 space-y-3 text-sm">
          <div v-for="item in draft.secrets" :key="`secret:${item.ref}`" class="grid grid-cols-3 gap-2"><input :value="item.ref" class="rounded border p-2" @change="renameSecretRef(item.ref, $event)" /><input v-model="item.title" class="rounded border p-2" /><label><input v-model="item.required" type="checkbox" /> required</label></div>
          <div v-for="item in draft.outputs" :key="`output:${item.name}`" class="grid grid-cols-4 gap-2"><input v-model="item.name" class="rounded border p-2" /><input v-model="item.title" class="rounded border p-2" /><input v-model="item.variable_ref" class="rounded border p-2" /><select v-model="item.value_type" class="rounded border p-2"><option>string</option><option>number</option><option>boolean</option><option>json</option></select></div>
          <div v-for="item in draft.asset_inputs" :key="`asset-input:${item.ref}`" class="grid grid-cols-3 gap-2"><input v-model="item.ref" class="rounded border p-2" /><input v-model="item.title" class="rounded border p-2" /><label><input v-model="item.required" type="checkbox" /> required</label></div>
          <div v-for="item in draft.asset_outputs" :key="`asset-output:${item.name}`" class="grid grid-cols-3 gap-2"><input v-model="item.name" class="rounded border p-2" /><input v-model="item.title" class="rounded border p-2" /><input v-model="item.asset_ref" class="rounded border p-2" /></div>
        </div>
      </section>
      </fieldset>
      <p v-if="error" role="alert" class="text-sm text-rose-700">{{ error }}</p>
      <button data-testid="compile-skill" type="submit" class="rounded-lg bg-violet-700 px-5 py-2.5 font-bold text-white disabled:opacity-50" :disabled="compiling || hasInvalidRename">{{ compiling ? '处理中…' : configurationState === 'compiled' ? '进入测试' : configurationState === 'configured' ? '重试编译' : t('Save configuration and compile') }}</button>
    </form>
  </main>
</template>
