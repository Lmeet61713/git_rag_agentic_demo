import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import ChatView from './ChatView.vue'
import { api } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    chatSessions: vi.fn().mockResolvedValue([]),
    createChatSession: vi.fn().mockResolvedValue({ id: 1, title: '新会话' }),
    chatMessages: vi.fn().mockResolvedValue([]),
    renameChatSession: vi.fn().mockResolvedValue({ id: 1, title: '新标题' }),
    deleteChatSession: vi.fn().mockResolvedValue(undefined),
  },
  chatStream: vi.fn(async (_payload, handlers) => {
    handlers.token({ content: '这是模型回答' })
    handlers.tool({ tool: 'doc_search' })
    handlers.sources({
      sources: [
        {
          project_id: 'owner/demo',
          path: 'README.md',
          file_type: 'doc',
          text: 'README 内容',
          score: 0.8,
        },
        {
          project_id: 'web',
          path: 'https://example.com/news',
          file_type: 'web',
          text: '新闻标题\n新闻摘要',
          score: 1,
        },
      ],
    })
    handlers.done({ mode: 'llm', tool: 'doc_search' })
  }),
}))

describe('ChatView', () => {
  it('sends a message and renders streamed answer with sources', async () => {
    const wrapper = mount(ChatView, { global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('项目有什么功能？')
    const sendButton = wrapper.findAll('button').find((button) => button.text() === '发送')
    await sendButton.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('项目有什么功能？')
    expect(wrapper.text()).toContain('这是模型回答')
    expect(wrapper.text()).toContain('owner/demo / README.md')
    expect(wrapper.text()).toContain('文档检索')
    expect(wrapper.text()).toContain('README 内容')
    expect(wrapper.text()).toContain('展开联网结果 (1)')
    expect(wrapper.text()).not.toContain('打开链接')
    const expandButton = wrapper.findAll('button').find((button) => button.text() === '展开联网结果 (1)')
    await expandButton.trigger('click')
    expect(wrapper.text()).toContain('打开链接')
    expect(
      wrapper.findAll('a').some((link) => link.attributes('href') === 'https://example.com/news'),
    ).toBe(true)
  })
})

describe('ChatView sessions', () => {
  it('loads and selects a history session', async () => {
    api.chatSessions.mockResolvedValue([{ id: 7, title: '历史会话' }])
    api.chatMessages.mockResolvedValue([
      { role: 'user', content: '上一轮问题', sources: [] },
      { role: 'assistant', content: '上一轮答案', sources: [], tool: 'repo_brief', mode: 'llm' },
    ])
    const wrapper = await mount(ChatView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('历史会话')
    expect(wrapper.text()).toContain('上一轮问题')
    expect(wrapper.text()).toContain('上一轮答案')
    expect(wrapper.text()).toContain('仓库列表')
  })

  it('collapses the session panel without leaving placeholder space', async () => {
    localStorage.clear()
    const wrapper = await mount(ChatView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.find('.session-panel.collapsed').exists()).toBe(false)
    const toggle = wrapper.findAll('button').find((button) => button.attributes('title') === '收起会话')
    await toggle.trigger('click')
    expect(wrapper.find('.session-panel.collapsed').exists()).toBe(true)
    expect(localStorage.getItem('chat.sessionsCollapsed')).toBe('1')
  })
})
