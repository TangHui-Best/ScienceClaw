<template>
  <main class="frame-page">
    <header>
      <h1>验收登记表单</h1>
      <p>请录入与来源采购订单一致的验收信息。</p>
    </header>

    <p v-if="loading" role="status">正在准备表单…</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <form v-if="!loading && !success" aria-label="验收登记" @submit.prevent="openConfirm">
      <div class="field">
        <label for="source-order-no">来源订单号</label>
        <input id="source-order-no" v-model="form.order_no" type="text" autocomplete="off">
      </div>

      <div class="field custom-select">
        <label for="supplier-search">供应商</label>
        <input
          id="supplier-search"
          v-model="form.supplier_name"
          type="search"
          role="combobox"
          aria-label="供应商"
          aria-controls="supplier-options"
          :aria-expanded="supplierOpen"
          autocomplete="off"
          @focus="supplierOpen = true"
          @input="supplierOpen = true"
        >
        <ul v-if="supplierOpen" id="supplier-options" role="listbox">
          <li v-for="supplier in filteredSuppliers" :key="supplier" role="option" :aria-label="supplier" @click="selectSupplier(supplier)">
            <button type="button" @click.stop="selectSupplier(supplier)">{{ supplier }}</button>
          </li>
        </ul>
      </div>

      <div class="field">
        <label for="contract-no">合同号</label>
        <input id="contract-no" v-model="form.contract_no" type="text" autocomplete="off">
      </div>
      <div class="field">
        <label for="acceptance-amount">验收金额</label>
        <input id="acceptance-amount" v-model="form.amount" type="number" step="0.01" min="0">
      </div>

      <div class="field custom-select">
        <span id="currency-label">币种</span>
        <button
          type="button"
          role="combobox"
          aria-label="币种"
          aria-controls="currency-options"
          :aria-expanded="currencyOpen"
          @click="currencyOpen = !currencyOpen"
        >
          {{ form.currency || '请选择币种' }}<span aria-hidden="true">⌄</span>
        </button>
        <ul v-if="currencyOpen" id="currency-options" role="listbox">
          <li v-for="currency in currencies" :key="currency" role="option" :aria-label="currency" @click="selectCurrency(currency)">
            <button type="button" @click.stop="selectCurrency(currency)">{{ currency }}</button>
          </li>
        </ul>
      </div>

      <div class="field">
        <label for="order-date">订单日期</label>
        <input id="order-date" v-model="form.order_date" type="date">
      </div>
      <div class="field full">
        <label for="acceptance-description">验收说明</label>
        <textarea id="acceptance-description" v-model="form.description" rows="4" />
      </div>
      <label class="checkbox full" for="acceptance-confirmed">
        <input id="acceptance-confirmed" v-model="form.confirmed" type="checkbox">
        已核对以上信息并确认无误
      </label>
      <div class="actions full"><button type="submit" aria-label="保存">保存</button></div>
    </form>

    <section v-if="modalOpen" class="modal-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="confirm-title" class="modal">
        <h2 id="confirm-title">确认提交验收登记？</h2>
        <p>提交后将写入系统 B 的验收记录。</p>
        <div class="modal-actions">
          <button type="button" @click="modalOpen = false">返回修改</button>
          <button type="button" class="primary" aria-label="确认提交" :disabled="saving" @click="confirmSave">确认提交</button>
        </div>
      </div>
    </section>

    <section v-if="success" role="status" class="success">
      <h2>验收登记已保存</h2>
      <p>来源订单号：{{ savedOrderNo }}</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  apiErrorMessage,
  getAcceptanceTask,
  saveAcceptanceRecord,
  type AcceptanceSourceOrder
} from '@/api/client'

const route = useRoute()
const taskId = computed(() => String(route.params.task_id || ''))
const token = computed(() => String(route.query.token || ''))
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref(false)
const modalOpen = ref(false)
const supplierOpen = ref(false)
const currencyOpen = ref(false)
const source = ref<AcceptanceSourceOrder | null>(null)
const savedOrderNo = ref('')
const currencies = ['CNY', 'USD', 'EUR', 'GBP']
const form = reactive({
  order_no: '', supplier_name: '', contract_no: '', amount: '', currency: '',
  order_date: '', description: '', confirmed: false
})

const filteredSuppliers = computed(() => {
  const options = [
    source.value?.supplier_name,
    '华东精密设备有限公司',
    '北辰数字技术有限公司',
    '青禾咨询有限公司'
  ].filter((value): value is string => Boolean(value))
  const unique = [...new Set(options)]
  const needle = form.supplier_name.trim().toLocaleLowerCase()
  return needle ? unique.filter((value) => value.toLocaleLowerCase().includes(needle)) : unique
})

function selectSupplier(value: string) {
  form.supplier_name = value
  supplierOpen.value = false
}

function selectCurrency(value: string) {
  form.currency = value
  currencyOpen.value = false
}

function openConfirm() {
  error.value = ''
  modalOpen.value = true
}

async function confirmSave() {
  saving.value = true
  error.value = ''
  try {
    await saveAcceptanceRecord(taskId.value, token.value, {
      order_no: form.order_no,
      supplier_name: form.supplier_name,
      contract_no: form.contract_no,
      amount: String(form.amount),
      currency: form.currency,
      order_date: form.order_date,
      description: form.description,
      confirmed: form.confirmed
    })
    savedOrderNo.value = form.order_no
    modalOpen.value = false
    success.value = true
  } catch (caught) {
    modalOpen.value = false
    error.value = apiErrorMessage(caught, '验收登记保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (!taskId.value || !token.value) {
    error.value = '验收任务授权信息不完整'
    loading.value = false
    return
  }
  try {
    const task = await getAcceptanceTask(taskId.value, token.value)
    source.value = task.source_order
  } catch (caught) {
    error.value = apiErrorMessage(caught, '验收任务加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.frame-page { min-height: 100vh; padding: 26px; box-sizing: border-box; color: #172033; background: white; }
header, form, .frame-page > p, .success { max-width: 940px; margin: 0 auto 20px; }
h1 { margin-bottom: 6px; }
form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; padding: 24px; border: 1px solid #d9e1eb; border-radius: 12px; }
.field { position: relative; display: flex; flex-direction: column; gap: 7px; }
.field label, .field > span { font-size: 13px; font-weight: 650; }
input, textarea, .custom-select > button { padding: 10px 11px; border: 1px solid #aab6c5; border-radius: 7px; background: white; font: inherit; }
.custom-select > button { display: flex; justify-content: space-between; text-align: left; }
.custom-select ul { position: absolute; z-index: 4; top: 66px; width: 100%; margin: 0; padding: 5px; list-style: none; background: white; border: 1px solid #aab6c5; border-radius: 7px; box-shadow: 0 8px 20px rgb(15 23 42 / 15%); }
.custom-select li button { width: 100%; padding: 8px; border: 0; background: white; text-align: left; }
.full { grid-column: 1 / -1; }
.checkbox { display: flex; gap: 9px; align-items: center; }
.actions { display: flex; justify-content: flex-end; }
.actions button, .primary { padding: 10px 22px; color: white; border: 0; border-radius: 7px; background: #2563eb; }
.modal-backdrop { position: fixed; z-index: 10; inset: 0; display: grid; place-items: center; background: rgb(15 23 42 / 50%); }
.modal { width: min(460px, calc(100% - 32px)); padding: 24px; box-sizing: border-box; border-radius: 12px; background: white; box-shadow: 0 24px 60px rgb(15 23 42 / 30%); }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.modal-actions button { padding: 9px 14px; border: 1px solid #aab6c5; border-radius: 7px; }
.success { padding: 24px; color: #166534; background: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; }
.error { color: #b42318; }
@media (max-width: 700px) { form { grid-template-columns: 1fr; } .full { grid-column: auto; } }
</style>
