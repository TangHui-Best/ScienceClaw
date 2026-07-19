import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'


const src = join(process.cwd(), 'src')
const views = join(src, 'views')


describe('first acceptance E2E page contracts', () => {
  it('provides the three bounded business pages', () => {
    expect(existsSync(`${views}/SystemAOrders.vue`)).toBe(true)
    expect(existsSync(`${views}/SystemBAcceptanceHost.vue`)).toBe(true)
    expect(existsSync(`${views}/SystemBAcceptanceFrame.vue`)).toBe(true)
  })

  it('registers the three stable routes without adding a navigation item', () => {
    const router = readFileSync(`${src}/router/index.ts`, 'utf8')
    const layout = readFileSync(`${views}/Layout.vue`, 'utf8')

    expect(router).toContain("path: '/system-a/orders'")
    expect(router).toContain("path: '/system-b/acceptance/:task_id'")
    expect(router).toContain("path: '/system-b/acceptance-frame/:task_id'")
    expect(layout).not.toContain('index="/system-a/orders"')
    expect(layout).not.toContain('index="/system-b/acceptance')
  })

  it('locks System A accessible filters, adjacent icon actions and row-scoped buttons', () => {
    const page = readFileSync(`${views}/SystemAOrders.vue`, 'utf8')

    expect(page).toContain('role="combobox"')
    expect(page).toContain('aria-label="业务类型"')
    expect(page).toContain('id="date-from"')
    expect(page).toContain('id="date-to"')
    expect(page).toContain('id="supplier-name"')
    expect(page).toContain('id="order-no"')
    expect(page).toContain('class="icon-actions"')
    expect(page).toContain('aria-label="查询"')
    expect(page).toContain('aria-label="重置"')
    expect(page).toContain(':data-order-no="row.order_no"')
    expect(page).toContain('>发起验收</button>')
    expect(page).toContain("window.open('about:blank', '_blank')")
  })

  it('locks the random host page and stable delayed iframe identity without sleeps', () => {
    const page = readFileSync(`${views}/SystemBAcceptanceHost.vue`, 'utf8')

    expect(page).toContain('采购订单验收登记')
    expect(page).toContain('title="验收登记表单"')
    expect(page).toContain('name="acceptance-form"')
    expect(page).toContain(':src="frameUrl"')
    expect(page).toContain('v-if="taskReady"')
    expect(page).not.toContain('setTimeout')
    expect(page).not.toContain('sleep(')
  })

  it('locks the iframe form controls and DOM confirmation modal', () => {
    const page = readFileSync(`${views}/SystemBAcceptanceFrame.vue`, 'utf8')
    const client = readFileSync(`${src}/api/client.ts`, 'utf8')

    for (const field of [
      'id="source-order-no"',
      'aria-label="供应商"',
      'id="contract-no"',
      'id="acceptance-amount"',
      'aria-label="币种"',
      'id="order-date"',
      'id="acceptance-description"',
      'id="acceptance-confirmed"'
    ]) {
      expect(page).toContain(field)
    }
    expect(page).toContain('type="number"')
    expect(page).toContain('<textarea')
    expect(page).toContain('type="checkbox"')
    expect(page).toContain('>保存</button>')
    expect(page).toContain('role="dialog"')
    expect(page).toContain('aria-modal="true"')
    expect(page).toContain('>确认提交</button>')
    expect(client).not.toContain('RPA_EVAL_ORACLE_TOKEN')
    expect(client).not.toContain('X-RPA-Eval-Oracle-Token')
  })
})
