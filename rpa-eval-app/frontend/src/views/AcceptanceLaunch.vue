<template>
  <main class="launch-page" aria-live="polite">
    <section v-if="errorMessage" class="launch-card" role="alert">
      <h1>验收任务创建失败</h1>
      <p>{{ errorMessage }}</p>
    </section>
    <section v-else class="launch-card">
      <h1>正在创建验收任务</h1>
      <p>请稍候，页面将自动进入采购订单验收登记。</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiClient, apiErrorMessage, type AcceptanceTaskCreated } from '@/api/client'

const route = useRoute()
const router = useRouter()
const errorMessage = ref('')

onMounted(async () => {
  const orderNo = String(route.query.order_no || '')
  if (!orderNo) {
    errorMessage.value = '缺少来源订单编号'
    return
  }
  try {
    const { data } = await apiClient.post<AcceptanceTaskCreated>(
      `/acceptance/orders/${encodeURIComponent(orderNo)}/tasks`
    )
    await router.replace(data.url)
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, '验收任务创建失败')
  }
})
</script>

<style scoped>
.launch-page { display: grid; min-height: 100vh; place-items: center; padding: 24px; background: #f4f7fb; }
.launch-card { width: min(520px, 100%); padding: 30px; border: 1px solid #d9e0ea; border-radius: 12px; background: #fff; text-align: center; }
.launch-card h1 { margin: 0 0 10px; }
.launch-card p { margin: 0; color: #667085; }
</style>
