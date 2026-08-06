import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App.vue'
import { api } from './api/client'
import { useAppStore } from './stores/app'

vi.mock('./api/client', () => ({
  api: {
    modelCatalog: vi.fn().mockResolvedValue([]),
    configs: vi.fn().mockResolvedValue([]),
    logout: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/repos' }),
  useRouter: () => ({ push: vi.fn() }),
  RouterLink: {
    name: 'RouterLink',
    props: ['to'],
    template: '<a><slot /></a>',
  },
  RouterView: {
    name: 'RouterView',
    template: '<div />',
  },
}))

describe('App layout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders header navigation instead of a sidebar', async () => {
    const pinia = createPinia()
    const store = useAppStore(pinia)
    store.user = { username: 'tester', avatar_url: '' }
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, ElementPlus],
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
          RouterView: { template: '<div />' },
        },
      },
    })
    await flushPromises()
    expect(wrapper.find('.app-aside').exists()).toBe(false)
    expect(wrapper.find('.app-header').exists()).toBe(true)
    expect(wrapper.find('.brand-name').text()).toBe('MyAgentic')
    expect(wrapper.text()).toContain('仓库')
    expect(wrapper.text()).toContain('聊天')
    expect(api.modelCatalog).toHaveBeenCalled()
  })
})
