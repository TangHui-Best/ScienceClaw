<template>
  <main class="host-page" aria-labelledby="acceptance-title">
    <header class="host-header">
      <p class="eyebrow">系统 B</p>
      <h1 id="acceptance-title">采购订单验收登记</h1>
      <p>任务编号：<code>{{ taskId }}</code></p>
    </header>

    <section v-if="errorMessage" class="status-card" role="alert">
      {{ errorMessage }}
    </section>
    <template v-else>
      <iframe
        v-for="frameIndex in nonBusinessFrameCount"
        :key="frameIndex"
        class="support-frame"
        :title="`验收操作帮助 ${frameIndex}`"
        :name="`acceptance-help-${frameIndex}`"
        :srcdoc="`<main><h2>操作帮助 ${frameIndex}</h2><p>请在业务表单中核对采购订单信息。</p></main>`"
      />
      <section class="form-shell" aria-label="验收登记业务区域">
        <div v-if="!showBusinessFrame" class="loading-card" aria-live="polite">
          正在加载验收登记表单…
        </div>
        <iframe
          v-else
          class="business-frame"
          title="验收登记表单"
          name="acceptance-form"
          :src="businessFrameUrl"
          data-testid="acceptance-form-frame"
        />
      </section>
    </template>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiClient, apiErrorMessage, type AcceptanceTask } from '@/api/client'

const route = useRoute()
const taskId = String(route.params.taskId)
const token = String(route.query.token || '')
const task = ref<AcceptanceTask | null>(null)
const errorMessage = ref('')
const showBusinessFrame = ref(false)
let frameTimer: number | undefined

const nonBusinessFrameCount = computed(() => task.value?.non_business_frame_count ?? 0)

const businessFrameUrl = computed(() =>
  `/system-b/acceptance-frame/${encodeURIComponent(taskId)}?token=${encodeURIComponent(token)}`
)

onMounted(async () => {
  try {
    const response = await apiClient.get<AcceptanceTask>(`/acceptance/tasks/${taskId}`, {
      params: { token }
    })
    task.value = response.data
    frameTimer = window.setTimeout(() => {
      showBusinessFrame.value = true
    }, 900)
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, '验收任务无效或已失效')
  }
})

onBeforeUnmount(() => {
  if (frameTimer !== undefined) window.clearTimeout(frameTimer)
})
</script>

<style scoped>
.host-page { min-height: 100vh; padding: 24px; background: #f4f7fb; }
.host-header, .status-card, .form-shell { max-width: 1120px; margin: 0 auto 18px; }
.host-header { padding: 22px 26px; border-radius: 12px; color: #fff; background: #17324d; }
.host-header h1 { margin: 4px 0 8px; }
.host-header p { margin: 0; }
.host-header code { color: #b9dcff; }
.eyebrow { color: #7fc0ff; font-weight: 700; letter-spacing: .08em; }
.support-frame { display: block; width: 1px; height: 1px; border: 0; opacity: .01; }
.form-shell { min-height: 590px; border: 1px solid #d9e0ea; border-radius: 12px; background: #fff; overflow: hidden; }
.loading-card, .status-card { padding: 28px; border-radius: 12px; background: #fff; }
.business-frame { display: block; width: 100%; height: 660px; border: 0; }
</style>
