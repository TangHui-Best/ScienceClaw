<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { saveRpaAgentSkill, testRpaAgentSkill } from '@/api/rpaAgent';
import SandboxPreview from '@/components/SandboxPreview.vue';
import RpaFlowGuide from '@/components/rpa/RpaFlowGuide.vue';
import RpaStepTimeline from '@/components/rpa/RpaStepTimeline.vue';
import { loadCreationSnapshot, saveCreationSnapshot } from '@/utils/rpaAgentSkillConfiguration';
import type { RpaAgentCreationStepViewModel } from '@/utils/rpaAgentCreationProjection';

const route = useRoute();
const sessionId = computed(() => String(route.query.sessionId || ''));
const { t } = useI18n();
const snapshot = loadCreationSnapshot(sessionId.value);
const creationSnapshot = ref(snapshot);
const inputJson = ref('{}');
const secretValues = ref<Record<string, string>>({});
const dataAssetValues = ref<Record<string, string>>({});
const running = ref(false);
const saving = ref(false);
const passed = ref(Boolean(snapshot?.testPassed));
const savedRef = ref(snapshot?.savedRef || '');
const result = ref<Record<string, any> | null>(null);
const error = ref('');
const testBrowserRef = ref('');

const persistSnapshot = (updates: Partial<NonNullable<typeof snapshot>>) => {
  if (!creationSnapshot.value) return;
  const next = { ...creationSnapshot.value, ...updates };
  saveCreationSnapshot(next);
  creationSnapshot.value = next;
};

const runSteps = computed<RpaAgentCreationStepViewModel[]>(() => {
  const raw = Array.isArray(result.value?.steps) ? result.value.steps : [];
  return raw.map((step: Record<string, any>, index: number) => ({
    id: String(step.trace_id || step.step_id || `run-step-${index + 1}`),
    ordinal: Number(step.sequence ?? step.ordinal ?? index + 1),
    kind: step.mode === 'agent' ? 'ai_instruction' : 'manual',
    title: String(step.title || step.trace_id || step.step_id || `Step ${index + 1}`),
    label: String(step.action_kind || step.mode || 'action'),
    description: `sequence ${step.sequence ?? index + 1}`,
    action: String(step.action_kind || step.mode || 'action'),
    captureStatus: 'captured',
    executionStatus: step.status === 'succeeded' ? 'succeeded' : step.status === 'failed' ? 'failed' : 'running',
    replayStatus: 'pending',
    compileMode: step.mode === 'agent' ? 'agent' : step.mode === 'playwright' ? 'playwright' : null,
    observations: [],
    isEffect: false,
    is_action: true,
    validation: { status: 'pending', details: '' },
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
  running.value = true;
  passed.value = false;
  error.value = '';
  try {
    const inputs = JSON.parse(inputJson.value) as Record<string, unknown>;
    const dataAssets = Object.fromEntries(Object.entries(dataAssetValues.value)
      .map(([ref, value]) => [ref, value.trim()] as const)
      .filter(([, value]) => Boolean(value)));
    const response = await testRpaAgentSkill(sessionId.value, {
      inputs,
      secrets: secretValues.value,
      data_assets: dataAssets,
    });
    if (response.artifact_hash !== snapshot.artifactHash) throw new Error('artifact_changed');
    result.value = response.run_result as Record<string, any>;
    testBrowserRef.value = String(
      (response.test_session as Record<string, unknown> | undefined)?.browser_session_ref || '',
    );
    passed.value = result.value?.status === 'succeeded';
    persistSnapshot({ testPassed: passed.value, savedRef: undefined });
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '测试回放失败';
  } finally {
    running.value = false;
    secretValues.value = {};
  }
};

const save = async () => {
  if (!passed.value || saving.value || savedRef.value) return;
  saving.value = true;
  try {
    const response = await saveRpaAgentSkill(sessionId.value);
    result.value = { ...(result.value || {}), save: response };
    savedRef.value = String(response.skill_ref || 'saved');
    persistSnapshot({ testPassed: true, savedRef: savedRef.value });
  } catch {
    error.value = '保存失败';
  } finally {
    saving.value = false;
  }
};
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-[#f5f6f7] dark:bg-[#161618]">
    <RpaFlowGuide
      current-step="test"
      :session-id="sessionId"
      :recorded-step-count="snapshot?.recordingSteps?.length || 0"
      :test-state="running ? 'running' : passed ? 'success' : result || error ? 'failed' : 'idle'"
      :skill-name="snapshot?.configurationDraft?.skill.name || ''"
    />
    <p v-if="!snapshot?.artifactHash" role="alert" class="m-6 rounded-xl bg-rose-50 p-4 text-rose-700">未找到已编译产物。</p>
    <div v-else class="flex min-h-0 flex-1">
      <aside class="flex w-[300px] flex-shrink-0 overflow-hidden bg-[#eff1f2] dark:bg-[#212122]">
        <RpaStepTimeline :steps="runSteps" title="逐步结果" mode="test" empty-message="开始测试后显示逐步结果。" />
      </aside>

      <main class="flex min-w-0 flex-1 flex-col px-5 py-4">
        <div class="relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-800 bg-[#1e1e1e] shadow-2xl">
          <SandboxPreview v-if="testBrowserRef" mode="browser" :is-live="true" :session-id="testBrowserRef" variant="inline" />
          <div v-else class="flex flex-1 items-center justify-center text-center text-sm text-gray-400">
            <div><p class="font-bold text-gray-200">独立测试浏览器</p><p class="mt-2">点击右侧“开始回放”后创建全新的 BrowserHostSession。</p></div>
          </div>
          <div v-if="running" class="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-purple-600 px-4 py-2 text-xs font-bold text-white">测试执行中…</div>
        </div>
      </main>

      <aside class="flex w-[320px] flex-shrink-0 flex-col overflow-y-auto border-l border-gray-200 bg-[#eff1f2] p-4 dark:border-gray-700 dark:bg-[#212122]">
        <section class="rounded-2xl bg-white p-4 shadow-sm dark:bg-[#272728]">
          <h1 class="font-extrabold">{{ t('Test replay') }}</h1>
          <p class="mt-1 text-xs text-gray-500">运行已编译的同一四文件产物，不会重新编译。</p>
          <code class="mt-3 block break-all text-[10px] text-gray-400">{{ snapshot.artifactHash }}</code>
          <label class="mt-4 block text-xs font-bold">Inputs JSON<textarea v-model="inputJson" class="mt-2 min-h-24 w-full rounded-xl border p-3 font-mono text-xs" :disabled="passed || Boolean(savedRef)" /></label>
          <label v-for="secret in snapshot.configurationDraft?.secrets || []" :key="secret.ref" class="mt-3 block text-xs font-bold">{{ secret.title }}<input v-model="secretValues[secret.ref]" :name="`secret-${secret.ref}`" type="password" autocomplete="new-password" class="mt-1 w-full rounded-xl border p-2 font-normal" :disabled="passed || Boolean(savedRef)" /></label>
          <label v-for="asset in snapshot.configurationDraft?.asset_inputs || []" :key="asset.ref" class="mt-3 block text-xs font-bold">{{ asset.title }} <code>{{ asset.ref }}</code><input v-model="dataAssetValues[asset.ref]" :name="`asset-${asset.ref}`" class="mt-1 w-full rounded-xl border p-2 font-normal" :required="asset.required" :disabled="passed || Boolean(savedRef)" placeholder="asset://…" /></label>
          <button data-testid="test-run" type="button" class="mt-4 w-full rounded-xl bg-violet-700 px-5 py-2.5 font-bold text-white disabled:opacity-40" :disabled="running || passed || Boolean(savedRef)" @click="run">{{ running ? '回放中…' : '开始回放' }}</button>
          <button data-testid="save-skill" type="button" class="mt-2 w-full rounded-xl bg-emerald-600 px-5 py-2.5 font-bold text-white disabled:opacity-40" :disabled="!passed || saving || Boolean(savedRef)" @click="save">{{ saving ? '保存中…' : t('Save SKILL') }}</button>
        </section>
        <section v-if="result || error" class="mt-4 rounded-2xl bg-white p-4 shadow-sm dark:bg-[#272728]">
          <h2 class="font-extrabold">运行结果：{{ result?.status || 'failed' }}</h2>
          <p v-if="result?.failed_step" class="mt-2 text-xs">失败步骤 {{ result.failed_step.trace_id }} / sequence {{ result.failed_step.sequence }} / {{ result.failed_step.phase }}</p>
          <p v-if="result?.error || error" class="mt-2 text-xs text-rose-700">{{ result?.error || error }}</p>
        </section>
      </aside>
    </div>
  </div>
</template>
