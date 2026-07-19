import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import Layout from './Layout.vue'

describe('Layout navigation', () => {
  it('opens the System A order search from the main sidebar', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/dashboard', component: { template: '<div />' } },
        { path: '/system-a/orders', component: { template: '<div />' } }
      ]
    })
    await router.push('/dashboard')
    await router.isReady()

    const wrapper = mount(Layout, {
      global: {
        plugins: [createPinia(), router, ElementPlus],
        stubs: { RouterView: true }
      }
    })

    const menuItem = wrapper
      .findAll('.el-menu-item')
      .find((item) => item.text() === '采购订单综合查询')

    expect(menuItem).toBeDefined()
    await menuItem!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/system-a/orders')
  })
})
