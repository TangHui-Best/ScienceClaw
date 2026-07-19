<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { saveRpaAgentSkill, testRpaAgentSkill } from '@/api/rpaAgent';
import { loadCreationSnapshot, saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';

type RunTimelineStep = {
  id: string; status: 'running' | 'succeeded' | 'failed'; title: string; label: string; description: string;
};

const route = useRoute(); const sessionId = computed(() => String(route.query.sessionId || ''));
const { t } = useI18n();
const snapshot = loadCreationSnapshot(sessionId.value);
const creationSnapshot = ref(snapshot);
const inputJson = ref('{}'); const secretValues = ref<Record<string, string>>({});
const dataAssetValues = ref<Record<string, string>>({});
const running = ref(false); const saving = ref(false); const passed = ref(Boolean(snapshot?.testPassed)); const savedRef = ref(snapshot?.savedRef || ''); const result = ref<Record<string, any> | null>(null); const error = ref('');

const persistSnapshot = (updates: Partial<NonNullable<typeof snapshot>>) => {
  if (!creationSnapshot.value) return;
  const next = { ...creationSnapshot.value, ...updates };
  saveCreationSnapshot(next);
  creationSnapshot.value = next;
};
const runSteps = computed<RunTimelineStep[]>(() => {
  const raw = Array.isArray(result.value?.steps) ? result.value.steps : [];
  return raw.map((step: Record<string, any>, index: number) => ({
    id: String(step.trace_id || `run-step-${index + 1}`),
    status: step.status === 'succeeded' ? 'succeeded' : step.status === 'failed' ? 'failed' : 'running',
    title: String(step.trace_id || `Step ${index + 1}`),
    label: String(step.action_kind || 'action'),
    description: `sequence ${step.sequence ?? index + 1}`,
  }));
});

const run = async () => {
  if (!snapshot?.artifactHash || running.value || passed.value || savedRef.value) return;
  const missingAsset = (snapshot.configurationDraft?.asset_inputs || [])
    .find((asset) => asset.required && !dataAssetValues.value[asset.ref]?.trim());
  if (missingAsset) {
    error.value = `缺少必填 DataAsset：${missingAsset.ref}`;
    return;
  }
  running.value = true; passed.value = false; error.value = '';
  try {
    const inputs = JSON.parse(inputJson.value) as Record<string, unknown>;
    const dataAssets = Object.fromEntries(Object.entries(dataAssetValues.value)
      .map(([ref, value]) => [ref, value.trim()] as const)
      .filter(([, value]) => Boolean(value)));
    const response = await testRpaAgentSkill(sessionId.value, { inputs, secrets: secretValues.value, data_assets: dataAssets });
    if (response.artifact_hash !== snapshot.artifactHash) throw new Error('artifact_changed');
    result.value = response.run_result as Record<string, any>;
    passed.value = result.value?.status === 'succeeded';
    persistSnapshot({ testPassed: passed.value, savedRef: undefined });
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '测试回放失败'; }
  finally { running.value = false; secretValues.value = {}; }
};

const save = async () => {
  if (!passed.value || saving.value || savedRef.value) return;
  saving.value = true;
  try {
    const response = await saveRpaAgentSkill(sessionId.value);
    result.value = { ...(result.value || {}), save: response };
    savedRef.value = String(response.skill_ref || 'saved');
    persistSnapshot({ testPassed: true, savedRef: savedRef.value });
  }
  catch { error.value = '保存失败'; }
  finally { saving.value = false; }
};
</script>

<template>
  <main class="mx-auto max-w-5xl p-6">
    <header><h1 class="text-2xl font-extrabold">{{ t('Test replay') }}</h1><p class="mt-1 text-sm text-gray-500">使用已编译的同一四文件产物；本页不会重新编译。</p></header>
    <p v-if="!snapshot?.artifactHash" role="alert" class="mt-6 rounded-lg bg-rose-50 p-4 text-rose-700">未找到已编译产物。</p>
    <template v-else>
      <section class="mt-6 rounded-xl bg-white p-5 shadow-sm dark:bg-[#252527]">
        <p class="text-xs text-gray-500">Artifact hash</p><code class="text-sm">{{ snapshot.artifactHash }}</code>
        <label class="mt-4 block text-sm font-bold">Inputs JSON<textarea v-model="inputJson" class="mt-2 min-h-28 w-full rounded-lg border p-3 font-mono text-sm" :disabled="passed || Boolean(savedRef)" /></label>
        <label v-for="secret in snapshot.configurationDraft?.secrets || []" :key="secret.ref" class="mt-4 block text-sm font-bold">
          {{ secret.title }}
          <input v-model="secretValues[secret.ref]" :name="`secret-${secret.ref}`" type="password" autocomplete="new-password" class="mt-2 w-full rounded-lg border p-2 font-normal" :disabled="passed || Boolean(savedRef)" />
        </label>
        <label v-for="asset in snapshot.configurationDraft?.asset_inputs || []" :key="asset.ref" class="mt-4 block text-sm font-bold">
          {{ asset.title }} <code class="text-xs">{{ asset.ref }}</code>
          <input v-model="dataAssetValues[asset.ref]" :name="`asset-${asset.ref}`" class="mt-2 w-full rounded-lg border p-2 font-normal" :required="asset.required" :disabled="passed || Boolean(savedRef)" placeholder="asset://…" />
        </label>
        <div class="mt-4 flex gap-3"><button data-testid="test-run" type="button" class="rounded-lg bg-violet-700 px-5 py-2 font-bold text-white disabled:opacity-40" :disabled="running || passed || Boolean(savedRef)" @click="run">{{ running ? '回放中…' : '开始回放' }}</button><button data-testid="save-skill" type="button" class="rounded-lg bg-emerald-600 px-5 py-2 font-bold text-white disabled:opacity-40" :disabled="!passed || saving || Boolean(savedRef)" @click="save">{{ t('Save SKILL') }}</button></div>
      </section>
      <section v-if="result || error" class="mt-4 rounded-xl bg-white p-5 shadow-sm dark:bg-[#252527]">
        <h2 class="font-extrabold">运行结果：{{ result?.status || 'failed' }}</h2>
        <p v-if="result?.failed_step" class="mt-2 text-sm">失败步骤 {{ result.failed_step.trace_id }} / sequence {{ result.failed_step.sequence }} / {{ result.failed_step.phase }}</p>
        <p v-if="result?.error || error" class="mt-2 text-sm text-rose-700">{{ result?.error || error }}</p>
      </section>
      <section v-if="runSteps.length" class="mt-4 h-80 overflow-hidden rounded-xl"><RpaStepTimeline :steps="runSteps" title="运行 Timeline" /></section>
    </template>
  </main>
</template>
