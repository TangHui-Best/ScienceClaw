import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SystemAOrders from '@/views/SystemAOrders.vue'
import SystemBAcceptanceFrame from '@/views/SystemBAcceptanceFrame.vue'
import SystemBAcceptanceHost from '@/views/SystemBAcceptanceHost.vue'


const mocks = vi.hoisted(() => ({
  listAcceptanceOrders: vi.fn(),
  startAcceptanceTask: vi.fn(),
  getAcceptanceTask: vi.fn(),
  saveAcceptanceRecord: vi.fn(),
  route: {
    params: { task_id: 'task-mounted' } as Record<string, string>,
    query: { token: 'task-token-mounted' } as Record<string, string>
  }
}))

vi.mock('@/api/client', () => ({
  apiErrorMessage: (_error: unknown, fallback: string) => fallback,
  listAcceptanceOrders: mocks.listAcceptanceOrders,
  startAcceptanceTask: mocks.startAcceptanceTask,
  getAcceptanceTask: mocks.getAcceptanceTask,
  saveAcceptanceRecord: mocks.saveAcceptanceRecord
}))

vi.mock('vue-router', () => ({
  useRoute: () => mocks.route
}))

const orders = [
  {
    order_no: 'PO-A', business_type: '设备采购', supplier_name: '供应商 A',
    contract_no: 'CT-A', amount: '10.00', currency: 'CNY',
    order_date: '2026-05-01', action_label: '发起验收'
  },
  {
    order_no: 'PO-B', business_type: '服务采购', supplier_name: '供应商 B',
    contract_no: 'CT-B', amount: '20.00', currency: 'USD',
    order_date: '2026-06-01', action_label: '发起验收'
  },
  {
    order_no: 'PO-C', business_type: '软件采购', supplier_name: '供应商 C',
    contract_no: 'CT-C', amount: '30.00', currency: 'EUR',
    order_date: '2026-07-01', action_label: '发起验收'
  }
]

beforeEach(() => {
  vi.clearAllMocks()
  mocks.route.params = { task_id: 'task-mounted' }
  mocks.route.query = { token: 'task-token-mounted' }
  mocks.listAcceptanceOrders.mockResolvedValue(orders)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('System A mounted interactions', () => {
  it('passes the entered filters and uses the clicked row to navigate the synchronous popup', async () => {
    let resolveTask!: (value: { url: string }) => void
    mocks.startAcceptanceTask.mockReturnValue(
      new Promise((resolve) => { resolveTask = resolve })
    )
    const popup = { location: { href: '' }, close: vi.fn() }
    const open = vi.fn(() => popup)
    vi.stubGlobal('open', open)
    const wrapper = mount(SystemAOrders)
    await flushPromises()

    await wrapper.get('[aria-label="业务类型"]').trigger('click')
    expect(wrapper.find('[role="option"][aria-label="设备采购"]').exists()).toBe(true)
    const businessOption = wrapper.get('[role="option"][aria-label="服务采购"]')
    await businessOption.trigger('click')
    await wrapper.get('#date-from').setValue('2026-06-01')
    await wrapper.get('#date-to').setValue('2026-06-30')
    await wrapper.get('#supplier-name').setValue('供应商 B')
    await wrapper.get('#order-no').setValue('PO-B')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.listAcceptanceOrders).toHaveBeenLastCalledWith({
      business_type: '服务采购',
      date_from: '2026-06-01',
      date_to: '2026-06-30',
      supplier_name: '供应商 B',
      order_no: 'PO-B'
    })

    const secondAction = wrapper.findAll('.row-action')[1]
    const click = secondAction.trigger('click')
    expect(open).toHaveBeenCalledWith('about:blank', '_blank')
    expect(mocks.startAcceptanceTask).toHaveBeenCalledWith('PO-B')
    resolveTask({ url: '/system-b/acceptance/random?token=random' })
    await click
    await flushPromises()
    expect(popup.location.href).toBe('/system-b/acceptance/random?token=random')
    expect(popup.close).not.toHaveBeenCalled()
  })

  it('closes the reserved popup when task creation fails', async () => {
    mocks.startAcceptanceTask.mockRejectedValue(new Error('failed'))
    const popup = { location: { href: '' }, close: vi.fn() }
    vi.stubGlobal('open', vi.fn(() => popup))
    const wrapper = mount(SystemAOrders)
    await flushPromises()

    await wrapper.findAll('.row-action')[0].trigger('click')
    await flushPromises()

    expect(mocks.startAcceptanceTask).toHaveBeenCalledWith('PO-A')
    expect(popup.close).toHaveBeenCalledOnce()
    expect(wrapper.get('[role="alert"]').text()).toContain('发起验收失败')
  })
})

describe('System B mounted interactions', () => {
  it('authorizes the host task before rendering the stable iframe identity', async () => {
    mocks.getAcceptanceTask.mockResolvedValue({
      task_id: 'task-mounted', profile: 'B', source_order: orders[1]
    })
    const wrapper = mount(SystemBAcceptanceHost)
    expect(wrapper.find('iframe').exists()).toBe(false)
    await flushPromises()

    expect(mocks.getAcceptanceTask).toHaveBeenCalledWith('task-mounted', 'task-token-mounted')
    const frame = wrapper.get('iframe')
    expect(frame.attributes('title')).toBe('验收登记表单')
    expect(frame.attributes('name')).toBe('acceptance-form')
    expect(frame.attributes('src')).toBe(
      '/system-b/acceptance-frame/task-mounted?token=task-token-mounted'
    )
  })

  it('keeps source fields blank, confirms in DOM, then saves the user-entered payload', async () => {
    mocks.getAcceptanceTask.mockResolvedValue({
      task_id: 'task-mounted', profile: 'B', source_order: orders[1]
    })
    mocks.saveAcceptanceRecord.mockResolvedValue({ task_id: 'task-mounted' })
    const wrapper = mount(SystemBAcceptanceFrame)
    await flushPromises()

    expect((wrapper.get('#source-order-no').element as HTMLInputElement).value).toBe('')
    expect((wrapper.get('#supplier-search').element as HTMLInputElement).value).toBe('')
    expect((wrapper.get('#contract-no').element as HTMLInputElement).value).toBe('')

    await wrapper.get('#source-order-no').setValue('PO-B')
    await wrapper.get('#supplier-search').setValue('供应商 B')
    await wrapper.get('[role="option"][aria-label="供应商 B"]').trigger('click')
    await wrapper.get('#contract-no').setValue('CT-B')
    await wrapper.get('#acceptance-amount').setValue('20.00')
    await wrapper.get('[aria-label="币种"]').trigger('click')
    expect(wrapper.find('[role="option"][aria-label="CNY"]').exists()).toBe(true)
    await wrapper.get('[role="option"][aria-label="USD"]').trigger('click')
    await wrapper.get('#order-date').setValue('2026-06-01')
    await wrapper.get('#acceptance-description').setValue('自动创建')
    await wrapper.get('#acceptance-confirmed').setValue(true)
    expect(wrapper.get('button[type="submit"]').attributes('aria-label')).toBe('保存')
    await wrapper.get('form').trigger('submit')

    expect(mocks.saveAcceptanceRecord).not.toHaveBeenCalled()
    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.get('[aria-label="确认提交"]').attributes('aria-label')).toBe('确认提交')
    const confirm = dialog.findAll('button').find((button) => button.text() === '确认提交')
    await confirm!.trigger('click')
    await flushPromises()

    expect(mocks.saveAcceptanceRecord).toHaveBeenCalledWith(
      'task-mounted',
      'task-token-mounted',
      {
        order_no: 'PO-B',
        supplier_name: '供应商 B',
        contract_no: 'CT-B',
        amount: '20',
        currency: 'USD',
        order_date: '2026-06-01',
        description: '自动创建',
        confirmed: true
      }
    )
    expect(wrapper.get('[role="status"]').text()).toContain('验收登记已保存')
  })
})
