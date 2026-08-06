import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import MemoryView from './MemoryView.vue'
import { api } from '../api/client'

describe('MemoryView', () => {
  it('loads and renders memory entries', async () => {
    vi.spyOn(api, 'memories').mockResolvedValue([
      {
        id: 1,
        content: '用户偏好 Python',
        project_id: 'owner/demo',
        session_id: null,
        type: 'long_term',
        updated_at: '2026-08-04 12:00:00',
      },
    ])
    const wrapper = mount(MemoryView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(api.memories).toHaveBeenCalled()
    expect(wrapper.text()).toContain('用户偏好 Python')
    expect(wrapper.text()).toContain('长期')
    expect(wrapper.text()).toContain('owner/demo')
  })
})
