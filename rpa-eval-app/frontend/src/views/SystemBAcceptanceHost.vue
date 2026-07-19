<template>
  <main class="host-page">
    <header>
      <p class="eyebrow">系统 B</p>
      <h1>采购订单验收登记</h1>
      <p>任务编号：<code>{{ taskId }}</code></p>
    </header>

    <aside aria-label="任务说明">
      <strong>登记说明</strong>
      <p>请在验收登记表单中核对业务字段并提交。本页的任务地址每次发起时都会变化。</p>
      <button type="button" @click="helpOpen = !helpOpen">{{ helpOpen ? '收起说明' : '查看说明' }}</button>
    </aside>

    <p v-if="loading" role="status">正在加载验收任务…</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <iframe
      v-if="taskReady"
      title="验收登记表单"
      name="acceptance-form"
      :src="frameUrl"
    />
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { apiErrorMessage, getAcceptanceTask } from '@/api/client'

const route = useRoute()
const taskId = computed(() => String(route.params.task_id || ''))
const token = computed(() => String(route.query.token || ''))
const taskReady = ref(false)
const loading = ref(true)
const error = ref('')
const helpOpen = ref(false)
const frameUrl = computed(
  () => `/system-b/acceptance-frame/${encodeURIComponent(taskId.value)}?token=${encodeURIComponent(token.value)}`
)

onMounted(async () => {
  if (!taskId.value || !token.value) {
    error.value = '验收任务授权信息不完整'
    loading.value = false
    return
  }
  try {
    await getAcceptanceTask(taskId.value, token.value)
    taskReady.value = true
  } catch (caught) {
    error.value = apiErrorMessage(caught, '验收任务加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.host-page { min-height: 100vh; padding: 30px; color: #172033; background: #eef2f7; }
header, aside, iframe, .host-page > p { display: block; width: min(1180px, 100%); margin: 0 auto 18px; box-sizing: border-box; }
header { padding: 20px 24px; background: white; border-radius: 12px; }
.eyebrow { margin: 0; color: #2563eb; font-weight: 700; }
h1 { margin: 6px 0; }
aside { padding: 14px 18px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; }
aside button { padding: 6px 10px; border: 1px solid #c8a436; border-radius: 6px; background: white; }
iframe { min-height: 720px; border: 1px solid #cbd5e1; border-radius: 12px; background: white; }
.error { color: #b42318; }
</style>
