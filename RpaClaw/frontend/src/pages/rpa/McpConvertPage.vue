<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ArrowLeft, Shield, Wand2, Save } from 'lucide-vue-next';
import { previewRpaMcpTool, createRpaMcpTool, type RpaMcpPreview } from '@/api/rpaMcp';
import { showErrorToast, showSuccessToast } from '@/utils/toast';

const route = useRoute();
const router = useRouter();
const sessionId = computed(() => typeof route.query.sessionId === 'string' ? route.query.sessionId : '');
const loading = ref(true);
const saving = ref(false);
const preview = ref<RpaMcpPreview | null>(null);
const toolName = ref('');
const description = ref('');
const postAuthStartUrl = ref('');
const allowedDomainsText = ref('');

const loadPreview = async () => {
  if (!sessionId.value) {
    showErrorToast('Missing sessionId');
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    const baseName = typeof route.query.skillName === 'string' && route.query.skillName.trim() ? route.query.skillName.trim() : 'rpa_tool';
    toolName.value = baseName;
    description.value = typeof route.query.skillDescription === 'string' ? route.query.skillDescription : '';
    preview.value = await previewRpaMcpTool(sessionId.value, { name: baseName, description: description.value });
    toolName.value = preview.value.name;
    description.value = preview.value.description || description.value;
    postAuthStartUrl.value = preview.value.post_auth_start_url || '';
    allowedDomainsText.value = (preview.value.allowed_domains || []).join('\n');
  } catch (error: any) {
    showErrorToast(error?.message || 'Failed to load MCP preview');
  } finally {
    loading.value = false;
  }
};

const saveTool = async () => {
  if (!sessionId.value) return;
  saving.value = true;
  try {
    await createRpaMcpTool(sessionId.value, {
      name: toolName.value,
      description: description.value,
      post_auth_start_url: postAuthStartUrl.value,
      allowed_domains: allowedDomainsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    });
    showSuccessToast('Converted tool saved');
    router.push('/chat/tools');
  } catch (error: any) {
    showErrorToast(error?.message || 'Failed to save MCP tool');
  } finally {
    saving.value = false;
  }
};

onMounted(loadPreview);
</script>

<template>
  <div class="min-h-screen bg-[#f5f7fb] text-slate-900 dark:bg-[#101115] dark:text-slate-100">
    <div class="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
      <div class="mb-6 flex items-center justify-between gap-4">
        <button class="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold dark:border-white/10 dark:bg-white/5" @click="router.back()">
          <ArrowLeft :size="16" />
          Back
        </button>
        <button class="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-[#8930b0] to-[#004be2] px-5 py-2 text-sm font-bold text-white" :disabled="saving || loading" @click="saveTool">
          <Save :size="16" />
          {{ saving ? 'Saving...' : 'Save as MCP Tool' }}
        </button>
      </div>

      <div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section class="space-y-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
          <div class="flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200">
              <Wand2 :size="18" />
            </div>
            <div>
              <h1 class="text-xl font-black">Convert to MCP Tool</h1>
              <p class="text-sm text-slate-500 dark:text-slate-400">Review the sanitized RPA steps before exposing them through the gateway.</p>
            </div>
          </div>

          <div v-if="loading" class="rounded-2xl border border-dashed border-slate-300 p-8 text-sm text-slate-500 dark:border-white/10">Loading preview...</div>

          <template v-else-if="preview">
            <label class="block space-y-2">
              <span class="text-sm font-semibold">Tool name</span>
              <input v-model="toolName" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none dark:border-white/10 dark:bg-white/5" />
            </label>
            <label class="block space-y-2">
              <span class="text-sm font-semibold">Description</span>
              <textarea v-model="description" rows="3" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none dark:border-white/10 dark:bg-white/5" />
            </label>
            <label class="block space-y-2">
              <span class="text-sm font-semibold">Post-login start URL</span>
              <input v-model="postAuthStartUrl" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none dark:border-white/10 dark:bg-white/5" />
            </label>
            <label class="block space-y-2">
              <span class="text-sm font-semibold">Allowed domains</span>
              <textarea v-model="allowedDomainsText" rows="4" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm outline-none dark:border-white/10 dark:bg-white/5" />
            </label>
          </template>
        </section>

        <aside class="space-y-4">
          <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
            <div class="flex items-center gap-3">
              <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200">
                <Shield :size="18" />
              </div>
              <div>
                <h2 class="text-base font-black">Sanitize report</h2>
                <p class="text-sm text-slate-500 dark:text-slate-400">Login actions are removed before the tool is shared.</p>
              </div>
            </div>
            <div v-if="preview" class="mt-4 space-y-3 text-sm">
              <div>
                <p class="font-semibold">Removed login steps</p>
                <p class="text-slate-500 dark:text-slate-400">{{ preview.sanitize_report.removed_steps.join(', ') || 'None' }}</p>
              </div>
              <div>
                <p class="font-semibold">Removed params</p>
                <p class="text-slate-500 dark:text-slate-400">{{ preview.sanitize_report.removed_params.join(', ') || 'None' }}</p>
              </div>
              <div>
                <p class="font-semibold">Warnings</p>
                <ul class="list-disc pl-5 text-slate-500 dark:text-slate-400">
                  <li v-for="warning in preview.sanitize_report.warnings" :key="warning">{{ warning }}</li>
                  <li v-if="preview.sanitize_report.warnings.length === 0">None</li>
                </ul>
              </div>
            </div>
          </section>

          <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
            <h2 class="text-base font-black">Retained steps</h2>
            <ol v-if="preview" class="mt-4 space-y-2 text-sm text-slate-600 dark:text-slate-300">
              <li v-for="(step, index) in preview.steps" :key="`${index}-${step.description || step.action}`" class="rounded-2xl bg-slate-50 px-3 py-2 dark:bg-white/5">
                {{ index + 1 }}. {{ step.description || step.action }}
              </li>
            </ol>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>
