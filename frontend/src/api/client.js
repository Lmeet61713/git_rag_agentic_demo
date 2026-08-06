import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

const API_ORIGIN = import.meta.env.VITE_API_ORIGIN || 'http://127.0.0.1:8000'

export const api = {
  async me() {
    const { data } = await http.get('/auth/me')
    return data
  },
  async login() {
    const { data } = await http.get(`${API_ORIGIN}/api/auth/login`)
    return data
  },
  async logout() {
    await http.post('/auth/logout')
  },
  async repos(refresh = false) {
    const { data } = await http.get('/repos', { params: { refresh } })
    return data
  },
  async indexRepo(owner, repo) {
    const { data } = await http.post(`/repos/${owner}/${repo}/index`)
    return data
  },
  async importRepo(url) {
    const { data } = await http.post('/repos/import', { url })
    return data
  },
  async deleteIndex(owner, repo) {
    await http.delete(`/repos/${owner}/${repo}/index`)
  },
  async job(jobId) {
    const { data } = await http.get(`/jobs/${jobId}`)
    return data
  },
  async syncLogs(owner, repo) {
    const { data } = await http.get(`/repos/${owner}/${repo}/logs`)
    return data
  },
  async configs() {
    const { data } = await http.get('/config/model')
    return data
  },
  async modelCatalog() {
    const { data } = await http.get('/config/model/catalog')
    return data
  },
  async saveConfig(payload) {
    const { data } = await http.put('/config/model', payload)
    return data
  },
  async memories(params) {
    const { data } = await http.get('/memory', { params })
    return data
  },
  async createMemory(payload) {
    const { data } = await http.post('/memory', payload)
    return data
  },
  async updateMemory(id, payload) {
    const { data } = await http.put(`/memory/${id}`, payload)
    return data
  },
  async deleteMemory(id) {
    await http.delete(`/memory/${id}`)
  },
  async chatSessions() {
    const { data } = await http.get('/chat/sessions')
    return data
  },
  async createChatSession(payload) {
    const { data } = await http.post('/chat/sessions', payload)
    return data
  },
  async chatMessages(sessionId) {
    const { data } = await http.get(`/chat/sessions/${sessionId}/messages`)
    return data
  },
  async renameChatSession(sessionId, payload) {
    const { data } = await http.put(`/chat/sessions/${sessionId}`, payload)
    return data
  },
  async deleteChatSession(sessionId) {
    await http.delete(`/chat/sessions/${sessionId}`)
  },
}

export async function chatStream(payload, handlers) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    throw new Error('聊天请求失败')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const block of events) {
      const lines = block.split('\n')
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
      const data = lines.find((line) => line.startsWith('data:'))?.slice(5).trim()
      if (data && handlers[event]) {
        handlers[event](JSON.parse(data))
      }
    }
  }
}
