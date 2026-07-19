<template>
  <main class="system-page">
    <header>
      <p class="eyebrow">系统 A</p>
      <h1>采购订单综合查询</h1>
      <p>组合业务条件查询订单，并在目标订单所在行发起验收。</p>
    </header>

    <form class="query-panel" aria-label="采购订单查询条件" @submit.prevent="runQuery">
      <div class="field custom-select">
        <span id="business-type-label">业务类型</span>
        <button
          type="button"
          role="combobox"
          aria-label="业务类型"
          aria-controls="business-type-options"
          :aria-expanded="businessTypeOpen"
          @click="businessTypeOpen = !businessTypeOpen"
        >
          {{ filters.business_type || '请选择业务类型' }}
          <span aria-hidden="true">⌄</span>
        </button>
        <ul v-if="businessTypeOpen" id="business-type-options" role="listbox">
          <li v-for="option in businessTypes" :key="option" role="option" :aria-label="option" @click="selectBusinessType(option)">
            <button type="button" @click.stop="selectBusinessType(option)">{{ option }}</button>
          </li>
        </ul>
      </div>

      <div class="field date-range">
        <label for="date-from">订单日期（起）</label>
        <input id="date-from" v-model="filters.date_from" type="date">
      </div>
      <div class="field date-range">
        <label for="date-to">订单日期（止）</label>
        <input id="date-to" v-model="filters.date_to" type="date">
      </div>
      <div class="field">
        <label for="supplier-name">供应商名称</label>
        <input id="supplier-name" v-model="filters.supplier_name" type="text" autocomplete="off">
      </div>
      <div class="field">
        <label for="order-no">订单编号</label>
        <input id="order-no" v-model="filters.order_no" type="text" autocomplete="off">
      </div>

      <div class="icon-actions" aria-label="查询操作">
        <button type="submit" class="icon-button primary" aria-label="查询" title="查询">
          <span aria-hidden="true">⌕</span>
        </button>
        <button type="button" class="icon-button" aria-label="重置" title="重置" @click="resetQuery">
          <span aria-hidden="true">↺</span>
        </button>
      </div>
    </form>

    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <section class="results" aria-labelledby="results-heading">
      <div class="section-heading">
        <h2 id="results-heading">查询结果</h2>
        <span>{{ rows.length }} 条</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>订单编号</th><th>供应商名称</th><th>合同编号</th><th>含税金额</th>
            <th>币种</th><th>订单日期</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.order_no" :data-order-no="row.order_no">
            <td>{{ row.order_no }}</td>
            <td>{{ row.supplier_name }}</td>
            <td>{{ row.contract_no }}</td>
            <td>{{ row.amount }}</td>
            <td>{{ row.currency }}</td>
            <td>{{ row.order_date }}</td>
            <td><button type="button" class="row-action" @click="startAcceptance(row)">发起验收</button></td>
          </tr>
        </tbody>
      </table>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  apiErrorMessage,
  listAcceptanceOrders,
  startAcceptanceTask,
  type AcceptanceSourceOrder
} from '@/api/client'

const businessTypes = ['设备采购', '服务采购', '软件采购', '备件采购']
const businessTypeOpen = ref(false)
const rows = ref<AcceptanceSourceOrder[]>([])
const error = ref('')
const filters = reactive({
  business_type: '',
  date_from: '',
  date_to: '',
  supplier_name: '',
  order_no: ''
})

function selectBusinessType(value: string) {
  filters.business_type = value
  businessTypeOpen.value = false
}

async function runQuery() {
  error.value = ''
  try {
    rows.value = await listAcceptanceOrders(
      Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
    )
  } catch (caught) {
    error.value = apiErrorMessage(caught, '查询采购订单失败')
  }
}

async function resetQuery() {
  Object.assign(filters, {
    business_type: '', date_from: '', date_to: '', supplier_name: '', order_no: ''
  })
  await runQuery()
}

async function startAcceptance(row: AcceptanceSourceOrder) {
  error.value = ''
  const popup = window.open('about:blank', '_blank')
  try {
    const task = await startAcceptanceTask(row.order_no)
    if (popup) {
      popup.location.href = task.url
    } else {
      window.location.assign(task.url)
    }
  } catch (caught) {
    popup?.close()
    error.value = apiErrorMessage(caught, '发起验收失败')
  }
}

onMounted(runQuery)
</script>

<style scoped>
.system-page { min-height: 100vh; padding: 32px; color: #182230; background: #f5f7fb; }
header, .query-panel, .results { max-width: 1280px; margin: 0 auto 20px; }
.eyebrow { margin: 0; color: #2563eb; font-weight: 700; }
h1 { margin: 6px 0; }
.query-panel { display: grid; grid-template-columns: repeat(6, minmax(150px, 1fr)); gap: 14px; padding: 20px; background: white; border: 1px solid #d8e0ea; border-radius: 12px; }
.field { position: relative; display: flex; flex-direction: column; gap: 7px; }
.field label, .field > span { font-size: 13px; font-weight: 650; }
input, .custom-select > button { min-height: 40px; padding: 0 11px; border: 1px solid #aab6c5; border-radius: 7px; background: white; text-align: left; }
.custom-select > button { display: flex; align-items: center; justify-content: space-between; }
.custom-select ul { position: absolute; z-index: 3; top: 64px; width: 100%; margin: 0; padding: 5px; list-style: none; background: white; border: 1px solid #aab6c5; border-radius: 7px; box-shadow: 0 8px 20px rgb(15 23 42 / 15%); }
.custom-select li button { width: 100%; padding: 8px; border: 0; background: white; text-align: left; }
.icon-actions { display: flex; align-items: end; gap: 8px; }
.icon-button { width: 40px; height: 40px; border: 1px solid #aab6c5; border-radius: 8px; background: white; font-size: 22px; }
.icon-button.primary { color: white; background: #2563eb; border-color: #2563eb; }
.results { overflow: auto; background: white; border: 1px solid #d8e0ea; border-radius: 12px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px; }
.section-heading h2 { margin: 0; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 13px 16px; border-top: 1px solid #e4e9f0; text-align: left; white-space: nowrap; }
th { color: #475569; background: #f8fafc; font-size: 13px; }
.row-action { padding: 7px 13px; color: #1d4ed8; border: 1px solid #93b4f7; border-radius: 6px; background: #eff6ff; }
.error { max-width: 1280px; margin: 0 auto 16px; color: #b42318; }
@media (max-width: 980px) { .query-panel { grid-template-columns: repeat(2, 1fr); } }
</style>
