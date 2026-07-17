<template>
  <main class="page" aria-labelledby="system-a-title">
    <section class="toolbar">
      <div>
        <p class="eyebrow">系统 A</p>
        <h1 id="system-a-title" class="page-title">采购订单综合查询</h1>
      </div>
    </section>

    <section class="panel query-panel" aria-label="采购订单查询条件">
      <el-form :inline="true" label-position="top" @submit.prevent="searchOrders">
        <el-form-item label="业务类型">
          <el-select
            v-model="filters.businessType"
            clearable
            placeholder="请选择业务类型"
            data-testid="business-type-select"
            style="width: 180px"
          >
            <el-option label="设备采购" value="设备采购" />
            <el-option label="服务采购" value="服务采购" />
            <el-option label="物料采购" value="物料采购" />
          </el-select>
        </el-form-item>
        <el-form-item label="下单日期">
          <el-date-picker
            v-model="filters.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            data-testid="order-date-range"
            style="width: 280px"
          />
        </el-form-item>
        <el-form-item label="供应商名称">
          <el-input
            v-model="filters.supplierName"
            clearable
            placeholder="请输入供应商名称"
            data-testid="supplier-name-input"
            style="width: 230px"
          />
        </el-form-item>
        <el-form-item label="订单编号">
          <el-input
            v-model="filters.orderNo"
            clearable
            placeholder="请输入订单编号"
            data-testid="order-no-input"
            style="width: 190px"
          />
        </el-form-item>
        <el-form-item label="操作" class="icon-actions">
          <el-button
            type="primary"
            circle
            native-type="submit"
            aria-label="查询"
            title="查询"
            data-testid="search-orders-button"
            :loading="loading"
          >
            <el-icon><Search /></el-icon>
          </el-button>
          <el-button
            circle
            aria-label="重置"
            title="重置"
            data-testid="reset-orders-button"
            @click="resetFilters"
          >
            <el-icon><RefreshLeft /></el-icon>
          </el-button>
        </el-form-item>
      </el-form>
    </section>

    <section class="panel" aria-label="采购订单查询结果">
      <div class="result-heading">
        <h2>查询结果</h2>
        <span aria-live="polite">共 {{ orders.length }} 条</span>
      </div>
      <el-table
        v-loading="loading"
        :data="orders"
        row-key="order_no"
        border
        stripe
        empty-text="暂无符合条件的采购订单"
        data-testid="order-results-table"
      >
        <el-table-column prop="order_no" label="订单编号" width="175" />
        <el-table-column prop="supplier_name" label="供应商名称" min-width="230" />
        <el-table-column prop="contract_no" label="合同编号" width="160" />
        <el-table-column label="含税金额" width="150" align="right">
          <template #default="{ row }">{{ formatAmount(row.amount, row.currency) }}</template>
        </el-table-column>
        <el-table-column prop="currency" label="币种" width="90" />
        <el-table-column prop="order_date" label="订单日期" width="130" />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button
              tag="a"
              type="primary"
              link
              :href="acceptanceLaunchPath(row)"
              target="_blank"
              rel="noopener"
              role="button"
              aria-label="发起验收"
              data-testid="start-acceptance"
              :data-order-no="row.order_no"
            >
              发起验收
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { RefreshLeft, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  apiClient,
  apiErrorMessage,
  type AcceptanceOrder
} from '@/api/client'

const loading = ref(false)
const orders = ref<AcceptanceOrder[]>([])
const filters = reactive({
  businessType: '',
  dateRange: [] as string[],
  supplierName: '',
  orderNo: ''
})

function formatAmount(amount: string, currency: string) {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2
  }).format(Number(amount))
}

async function searchOrders() {
  loading.value = true
  try {
    const { data } = await apiClient.get<AcceptanceOrder[]>('/acceptance/orders', {
      params: {
        business_type: filters.businessType || undefined,
        date_from: filters.dateRange[0] || undefined,
        date_to: filters.dateRange[1] || undefined,
        supplier_name: filters.supplierName.trim() || undefined,
        order_no: filters.orderNo.trim() || undefined
      }
    })
    orders.value = data
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '采购订单查询失败'))
  } finally {
    loading.value = false
  }
}

async function resetFilters() {
  filters.businessType = ''
  filters.dateRange = []
  filters.supplierName = ''
  filters.orderNo = ''
  await searchOrders()
}

function acceptanceLaunchPath(order: AcceptanceOrder) {
  return `/system-b/acceptance-launch?order_no=${encodeURIComponent(order.order_no)}`
}

onMounted(searchOrders)
</script>

<style scoped>
.page { padding: 24px; }
.toolbar { display: flex; align-items: end; justify-content: space-between; margin-bottom: 18px; }
.eyebrow { margin: 0 0 4px; color: #2f81f7; font-size: 13px; font-weight: 700; letter-spacing: .08em; }
.page-title { margin: 0; font-size: 24px; }
.panel { margin-bottom: 18px; padding: 20px; border: 1px solid #d9e0ea; border-radius: 10px; background: #fff; }
.query-panel :deep(.el-form-item) { margin-bottom: 0; }
.icon-actions :deep(.el-form-item__content) { gap: 2px; }
.result-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-heading h2 { margin: 0; font-size: 18px; }
.result-heading span { color: #667085; }
</style>
