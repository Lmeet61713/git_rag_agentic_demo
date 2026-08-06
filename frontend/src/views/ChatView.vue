<script setup>
import { nextTick, onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { ElMessage, ElMessageBox } from 'element-plus'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-vue-next'
import { api, chatStream } from '../api/client'

const messages = ref([])
const input = ref('')
const sending = ref(false)
const listRef = ref(null)
const sessions = ref([])
const currentSessionId = ref(null)
const loadingSessions = ref(false)
const loadingMessages = ref(false)
const sessionCollapsed = ref(localStorage.getItem('chat.sessionsCollapsed') === '1')

function toggleSessions() {
  sessionCollapsed.value = !sessionCollapsed.value
  localStorage.setItem('chat.sessionsCollapsed', sessionCollapsed.value ? '1' : '0')
}

function fileUrl(source) {
  const [owner, repo] = source.project_id.split('/')
  const path = source.path.split('/').map(encodeURIComponent).join('/')
  return `/api/files/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${path}`
}

function renderMarkdown(content) {
  return DOMPurify.sanitize(marked.parse(content || ''))
}

function inferMode(content) {
  if (content.startsWith('当前 DeepSeek 模型配置') || content.startsWith('当前 阿里云 DashScope 模型配置')) {
    return 'config_error'
  }
  return content.includes('本地检索兜底')
    || content.startsWith('当前未配置可用模型')
    || content.startsWith('当前模型')
    || content.startsWith('未找到与问题相关')
    ? 'fallback'
    : 'llm'
}

function toolText(tool) {
  return {
    search: '向量检索',
    repo_tech: '技术栈检索',
    overview: '项目概览',
    image_search: '图片检索',
    doc_search: '文档检索',
    repo_brief: '仓库列表',
    web_search: '联网搜索',
    read_file: '读取文件',
    direct: '直接回答',
    project_intro: '项目介绍',
    app_guide: '应用咨询',
    general_chat: '日常闲聊',
    config_error: '模型配置',
    repo_meta: '仓库元数据',
  }[tool] || '检索'
}

function scrollBottom() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    sessions.value = await api.chatSessions()
    if (!currentSessionId.value && sessions.value.length) {
      await selectSession(sessions.value[0].id)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '会话列表加载失败')
  } finally {
    loadingSessions.value = false
  }
}

async function selectSession(sessionId) {
  if (sessionId === currentSessionId.value) return
  currentSessionId.value = sessionId
  loadingMessages.value = true
  messages.value = []
  try {
    const items = await api.chatMessages(sessionId)
    messages.value = items.map((item) => ({
      role: item.role,
      content: item.content,
      sources: item.sources || [],
      streaming: false,
      mode: item.mode || inferMode(item.content),
      tool: item.tool || '',
    }))
    scrollBottom()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '历史消息加载失败')
  } finally {
    loadingMessages.value = false
  }
}

async function newSession() {
  try {
    const session = await api.createChatSession({ title: '新会话' })
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    messages.value = []
    input.value = ''
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '新建会话失败')
  }
}

async function renameSession(session) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      inputValue: session.title,
      inputValidator: (title) => (title.trim() ? true : '标题不能为空'),
    })
    const updated = await api.renameChatSession(session.id, { title: value.trim() })
    const item = sessions.value.find((entry) => entry.id === session.id)
    if (item) item.title = updated.title
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error.response?.data?.detail || '重命名失败')
    }
  }
}

async function removeSession(session) {
  try {
    await ElMessageBox.confirm(`确定删除会话「${session.title}」吗？`, '删除会话', { type: 'warning' })
    await api.deleteChatSession(session.id)
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    if (currentSessionId.value === session.id) {
      currentSessionId.value = null
      messages.value = []
      if (sessions.value.length) {
        await selectSession(sessions.value[0].id)
      }
    }
    ElMessage.success('已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  messages.value.push({ role: 'user', content: text, sources: [] })
  messages.value.push({ role: 'assistant', content: '', sources: [], streaming: true, tool: '' })
  input.value = ''
  const current = messages.value[messages.value.length - 1]
  try {
    await chatStream({ message: text, session_id: currentSessionId.value }, {
      start(data) {
        if (!currentSessionId.value && data.session_id) {
          currentSessionId.value = data.session_id
        }
      },
      token(data) {
        current.content += data.content
        current.mode = inferMode(current.content)
      },
      tool(data) {
        current.tool = data.tool || current.tool
      },
      sources(data) {
        current.sources = data.sources || []
      },
      done(data) {
        current.streaming = false
        current.mode = data.mode || inferMode(current.content)
        current.tool = data.tool || current.tool
        if (data.session_id && !sessions.value.some((item) => item.id === data.session_id)) {
          const title = text.length > 24 ? `${text.slice(0, 24)}...` : text
          sessions.value.unshift({ id: data.session_id, title })
          api.renameChatSession(data.session_id, { title }).catch(() => {})
        }
      },
    })
  } catch (error) {
    current.content = '请求失败，请确认后端已启动。'
    current.streaming = false
    ElMessage.error(error.message)
  } finally {
    sending.value = false
    scrollBottom()
  }
}

onMounted(loadSessions)
</script>

<template>
  <div class="page chat-page">
    <div class="chat-layout">
      <aside class="session-panel" :class="{ collapsed: sessionCollapsed }">
        <div class="session-toolbar">
          <strong>会话</strong>
          <el-button size="small" type="primary" @click="newSession">新建会话</el-button>
        </div>
        <div class="session-list" v-loading="loadingSessions">
          <div
            v-for="session in sessions"
            :key="session.id"
            class="session-item"
            :class="{ active: session.id === currentSessionId }"
            @click="selectSession(session.id)"
          >
            <span v-if="session.id === currentSessionId" class="session-badge">当前</span>
            <span class="session-title">{{ session.title }}</span>
            <span class="session-actions">
              <el-button text size="small" @click.stop="renameSession(session)">重命名</el-button>
              <el-button text size="small" type="danger" @click.stop="removeSession(session)">删除</el-button>
            </span>
          </div>
          <div v-if="!loadingSessions && !sessions.length" class="session-empty">
            暂无会话，点击“新建会话”开始。
          </div>
        </div>
      </aside>
      <div class="chat-main">
        <div class="toolbar chat-toolbar">
          <h2>Agent 问答</h2>
          <el-button
            text
            circle
            size="small"
            :title="sessionCollapsed ? '展开会话' : '收起会话'"
            @click="toggleSessions"
          >
            <PanelLeftClose v-if="!sessionCollapsed" :size="16" />
            <PanelLeftOpen v-else :size="16" />
          </el-button>
        </div>
        <div ref="listRef" class="message-list" v-loading="loadingMessages">
          <div v-for="(msg, index) in messages" :key="index" class="message-row" :class="msg.role">
            <div class="bubble">
              <div v-if="msg.role === 'assistant'" class="markdown-body" v-html="renderMarkdown(msg.content)" />
              <div v-else>{{ msg.content }}</div>
              <div v-if="msg.streaming && !msg.content" class="thinking">思考中...</div>
              <div v-if="msg.tool || msg.mode === 'fallback'" class="answer-meta">
                <el-tag v-if="msg.tool" size="small" type="warning" effect="plain">
                  {{ toolText(msg.tool) }}
                </el-tag>
                <el-tag v-if="msg.mode === 'fallback'" size="small" type="info" effect="plain">
                  本地检索兜底
                </el-tag>
                <el-tag v-else-if="msg.mode === 'fallback_llm'" size="small" type="warning" effect="plain">
                  Ollama 保底
                </el-tag>
              </div>
              <div v-if="msg.sources && msg.sources.length" class="sources">
                <div class="sources-title">来源</div>
                <div v-for="(source, si) in msg.sources" :key="si" class="source-card">
                  <div class="source-head">
                    <strong>{{ source.project_id }} / {{ source.path }}</strong>
                    <el-tag size="small" effect="plain">{{ source.file_type }}</el-tag>
                  </div>
                  <div class="source-score">相关度 {{ Number(source.score || 0).toFixed(2) }}</div>
                  <p v-if="source.text" class="source-snippet">{{ source.text.slice(0, 120) }}</p>
                  <el-link
                    :href="source.file_type === 'web' ? source.path : fileUrl(source)"
                    target="_blank"
                    type="primary"
                  >
                    {{ source.file_type === 'web' ? '打开链接' : source.file_type === 'image' ? '查看图片' : '查看文件' }}
                  </el-link>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!loadingMessages && !messages.length" class="chat-empty">
            从左侧选择会话，或新建会话后开始提问。
          </div>
        </div>
        <div class="input-bar">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            placeholder="例如：这个项目大致有什么？"
            @keydown.enter.exact.prevent="send"
          />
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  max-width: 1440px;
  height: calc(100vh - 90px);
}

.chat-layout {
  display: flex;
  gap: 16px;
  height: 100%;
}

.session-panel {
  width: 280px;
  min-width: 0;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  transition: width 0.18s ease, border-color 0.18s ease;
}

.session-panel.collapsed {
  width: 0;
  border-color: transparent;
}

.session-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid var(--border);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.session-item:hover {
  background: var(--surface-muted);
  border-left-color: #b8d8d2;
}

.session-item.active {
  background: var(--accent-weak);
  border-left-color: var(--accent);
  box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.12);
}

.session-badge {
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1;
  padding: 3px 5px;
  border-radius: 4px;
  color: var(--accent-strong);
  background: #d8f3ec;
}

.session-item.active .session-title {
  color: var(--accent-strong);
  font-weight: 600;
}

.session-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-actions {
  display: flex;
  flex-shrink: 0;
}

.session-empty,
.chat-empty {
  padding: 24px 12px;
  color: var(--text-muted);
  text-align: center;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.chat-toolbar {
  margin-bottom: 12px;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}

.message-row {
  display: flex;
  margin-bottom: 12px;
}

.message-row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 82%;
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-row.user .bubble {
  background: var(--accent-weak);
  border-color: #99f6e4;
}

.markdown-body {
  white-space: normal;
}

.markdown-body :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
}

.thinking {
  color: var(--text-muted);
}

.answer-meta {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.sources {
  margin-top: 10px;
}

.sources-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.source-head strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-score {
  font-size: 11px;
  color: var(--text-muted);
}

.source-snippet {
  margin: 4px 0;
  font-size: 12px;
  color: var(--text-muted);
}

.input-bar {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
</style>
