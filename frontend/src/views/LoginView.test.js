import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import { api } from '../api/client'
import LoginView from './LoginView.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { error: 'invalid_state' } }),
}))

vi.mock('../api/client', () => ({
  api: {
    login: vi.fn().mockResolvedValue({ login_url: 'https://github.com/login/oauth/authorize' }),
  },
}))

describe('LoginView', () => {
  it('shows a friendly message for invalid_state', () => {
    const wrapper = mount(LoginView, { global: { plugins: [ElementPlus] } })
    expect(wrapper.text()).toContain('登录状态已失效')
  })

  it('opens the GitHub authorization url', async () => {
    const originalHref = window.location.href
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { href: '' },
    })
    const wrapper = mount(LoginView, { global: { plugins: [ElementPlus] } })
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(window.location.href).toContain('github.com/login/oauth/authorize')
    expect(api.login).toHaveBeenCalled()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { href: originalHref },
    })
  })
})
