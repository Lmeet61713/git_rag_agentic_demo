import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import ConfigView from './ConfigView.vue'
import { api } from '../api/client'

describe('ConfigView', () => {
  it('loads model config and saves changes', async () => {
    const catalogSpy = vi.spyOn(api, 'modelCatalog').mockResolvedValue([
      {
        provider: 'deepseek',
        label: 'DeepSeek',
        models: ['deepseek-chat', 'deepseek-reasoner'],
        base_url: 'https://api.deepseek.com',
        requires_api_key: true,
      },
      {
        provider: 'dashscope',
        label: '阿里云 DashScope',
        models: ['qwen-max', 'qwen-plus'],
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        requires_api_key: true,
      },
      {
        provider: 'ollama',
        label: '本地 Ollama',
        models: ['deepseek-r1:7b', 'qwen3.5:2b'],
        base_url: 'http://127.0.0.1:11434',
        requires_api_key: false,
      },
    ])
    const configsSpy = vi.spyOn(api, 'configs').mockResolvedValue([
      {
        provider: 'deepseek',
        model_name: 'deepseek-chat',
        base_url: 'https://api.deepseek.com',
        is_active: true,
      },
    ])
    const saveSpy = vi.spyOn(api, 'saveConfig').mockResolvedValue({})
    const wrapper = mount(ConfigView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('deepseek-chat')
    expect(catalogSpy).toHaveBeenCalled()
    const saveButton = wrapper.findAll('button').find((button) => button.text() === '保存')
    await saveButton.trigger('click')
    await flushPromises()
    expect(saveSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: 'deepseek',
        model_name: 'deepseek-chat',
      }),
    )
    expect(configsSpy).toHaveBeenCalledTimes(2)
  })
})
