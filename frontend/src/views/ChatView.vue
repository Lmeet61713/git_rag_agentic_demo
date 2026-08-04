<script setup>
import { nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { chatStream } from '../api/client'

const messages = ref([])
const input = ref('')
const sending = ref(false)
const listRef = ref(null)

function fileUrl(source) {
  const [owner, repo] = source.project_id.split('/')
  return `/api/files/${owner}/${repo}/${source.path}`
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  sending.value = true
  messages.value.push({ role: 'user', content: text, sources: [] })
  messages.value.push({ role: 'assistant', content: '', sources: [], streaming: true })
  input.value = ''
  const current = messages.value[messages.value.length - 1]
  try {
    await chatStream({ message: text }, {
      message(data) {
        current.content += data.content
      },
      sources(data) {
        current.sources = data.sources || []
      },
      done() {
        current.streaming = false
      },
    })
  } catch (error) {
    current.content = '请求失败，请确认后端已启动。'
    current.streaming = false
    ElMessage.error(error.message)
  } finally {
    sending.value = false
    nextTick(() => {
      if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
    })
  }
}
</script>

<template>
  <div class="page chat-page">
    <div class="toolbar"><h2>Agent 问答</h2></div>
    <div ref="listRef" class="message-list">
      <div v-for="(msg, index) in messages" :key="index" class="message-row" :class="msg.role">
        <div class="bubble">
          <div>{{ msg.content || (msg.streaming ? '思考中...' : '') }}</div>
          <div v-if="msg.sources && msg.sources.length" class="sources">
            <div v-for="(source, si) in msg.sources" :key="si" class="source-card">
              <strong>{{ source.project_id }} / {{ source.path }}</strong>
              <el-link
                v-if="source.file_type === 'image'"
                :href="fileUrl(source)"
                target="_blank"
                type="primary"
              >
                查看图片
              </el-link>
              <pre>{{ source.text }}</pre>
            </div>
          </div>
        </div>
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
</template>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 100px);
}

.message-list {
  flex: 1;
  overflow-y: auto;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
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
  max-width: 80%;
  background: #f0f2f5;
  border-radius: 8px;
  padding: 10px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-row.user .bubble {
  background: #d9ecff;
}

.input-bar {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
</style>
