import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import ReposView from './ReposView.vue'

vi.mock('../api/client', () => ({
  api: {
    repos: vi.fn().mockResolvedValue([
      {
        full_name: 'owner/demo',
        owner: 'owner',
        repo: 'demo',
        default_branch: 'main',
        index_status: 'indexed',
        last_indexed_at: '2026-08-04 12:00:00',
        summary: '索引完成：10 个文件，12 个向量分块。',
      },
    ]),
    syncLogs: vi.fn().mockResolvedValue([]),
  },
}))

describe('ReposView', () => {
  it('renders repos and indexed status', async () => {
    const wrapper = mount(ReposView, {
      global: { plugins: [ElementPlus, createPinia()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('owner/demo')
    expect(wrapper.text()).toContain('已入库')
    expect(wrapper.text()).toContain('重新入库')
  })
})
