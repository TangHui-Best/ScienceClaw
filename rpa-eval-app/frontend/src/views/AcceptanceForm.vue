<template>
  <main class="frame-page" aria-labelledby="form-title">
    <header>
      <h1 id="form-title">验收登记表单</h1>
      <p v-if="task">来源任务：{{ task.task_id }}</p>
    </header>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />
    <el-alert
      v-if="saved"
      title="保存成功"
      description="验收登记记录已写入业务系统。"
      type="success"
      show-icon
      :closable="false"
      data-testid="acceptance-save-success"
    />

    <el-form v-if="task && !saved" label-position="top" class="acceptance-form">
      <div class="form-grid">
        <el-form-item label="订单编号">
          <el-input v-model="form.order_no" data-testid="acceptance-order-no" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-select
            v-model="form.supplier_name"
            filterable
            placeholder="搜索并选择供应商"
            data-testid="acceptance-supplier"
            style="width: 100%"
          >
            <el-option v-for="supplier in supplierOptions" :key="supplier" :label="supplier" :value="supplier" />
          </el-select>
        </el-form-item>
        <el-form-item label="合同编号">
          <el-input v-model="form.contract_no" data-testid="acceptance-contract-no" />
        </el-form-item>
        <el-form-item label="验收金额">
          <el-input
            v-model="form.amount"
            type="number"
            step="0.01"
            min="0"
            data-testid="acceptance-amount"
          />
        </el-form-item>
        <el-form-item label="币种">
          <el-select v-model="form.currency" placeholder="请选择币种" data-testid="acceptance-currency" style="width: 100%">
            <el-option label="人民币（CNY）" value="CNY" />
            <el-option label="美元（USD）" value="USD" />
            <el-option label="欧元（EUR）" value="EUR" />
          </el-select>
        </el-form-item>
        <el-form-item label="订单日期">
          <el-date-picker
            v-model="form.order_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择订单日期"
            data-testid="acceptance-order-date"
            style="width: 100%"
          />
        </el-form-item>
      </div>
      <el-form-item label="备注">
        <el-input v-model="form.note" type="textarea" :rows="3" data-testid="acceptance-note" />
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="form.confirmed" data-testid="acceptance-confirmed">我已核对以上验收信息</el-checkbox>
      </el-form-item>
      <el-button type="primary" data-testid="acceptance-save" @click="confirmDialogVisible = true">
        保存
      </el-button>
    </el-form>

    <el-dialog v-model="confirmDialogVisible" title="确认提交" width="420px" data-testid="acceptance-confirm-dialog">
      <p>确认保存当前验收登记信息吗？</p>
      <template #footer>
        <el-button @click="confirmDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" data-testid="acceptance-confirm-submit" @click="saveRecord">
          确认提交
        </el-button>
      </template>
    </el-dialog>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  apiClient,
  apiErrorMessage,
  type AcceptanceRecordInput,
  type AcceptanceTask
} from '@/api/client'

const route = useRoute()
const taskId = String(route.params.taskId)
const token = String(route.query.token || '')
const task = ref<AcceptanceTask | null>(null)
const errorMessage = ref('')
const saving = ref(false)
const saved = ref(false)
const confirmDialogVisible = ref(false)
const form = reactive({
  order_no: '',
  supplier_name: '',
  contract_no: '',
  amount: '',
  currency: '',
  order_date: '',
  note: '',
  confirmed: false
})

const supplierOptions = computed(() => {
  const source = task.value?.order.supplier_name
  return [source, '远航工业服务有限公司', '启明供应链有限公司'].filter((value): value is string => Boolean(value))
})

onMounted(async () => {
  try {
    const response = await apiClient.get<AcceptanceTask>(`/acceptance/tasks/${taskId}`, {
      params: { token }
    })
    task.value = response.data
  } catch (error) {
    errorMessage.value = apiErrorMessage(error, '验收任务无效或已失效')
  }
})

async function saveRecord() {
  saving.value = true
  try {
    const payload: AcceptanceRecordInput = {
      ...form
    }
    await apiClient.post(`/acceptance/tasks/${taskId}/records`, payload, {
      params: { token }
    })
    confirmDialogVisible.value = false
    saved.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '验收登记保存失败'))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.frame-page { min-height: 100vh; box-sizing: border-box; padding: 24px 30px; background: #fff; }
header { margin-bottom: 18px; }
header h1 { margin: 0 0 6px; font-size: 22px; }
header p { margin: 0; color: #667085; }
.acceptance-form { margin-top: 20px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 22px; }
@media (max-width: 760px) { .form-grid { grid-template-columns: 1fr; } }
</style>
