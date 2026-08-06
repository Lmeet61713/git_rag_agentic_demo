<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'

const store = useAppStore()
let pollTimer = null
let activeRepo = null
const logsVisible = ref(false)
const logs = ref([])
const logRepo = ref(null)
const importVisible = ref(false)
const importUrl = ref('')
const importing = ref(false)

function statusType(status) {
  return { indexed: 'success', indexing: 'warning', failed: 'danger', not_indexed: 'info' }[status] || 'info'
}

function statusText(status) {
  return { indexed: '已入库', indexing: '索引中', failed: '失败', not_indexed: '未入库' }[status] || status
}

async function loadRepos(refresh = false) {
  try {
    await store.loadRepos(refresh)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '仓库列表加载失败')
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollIndexStatus() {
  try {
    await store.loadRepos(false)
    const current = store.repos.find((item) => item.full_name === activeRepo?.full_name)
    if (!current || current.index_status !== 'indexing') {
      stopPolling()
      activeRepo = null
    }
  } catch {
    // 保留轮询，下一次刷新再尝试。
  }
}

async function index(repo) {
  try {
    await store.indexRepo(repo)
    ElMessage.success('入库任务已启动')
    activeRepo = repo
    stopPolling()
    pollTimer = setInterval(pollIndexStatus, 3000)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '入库任务启动失败')
  }
}

async function remove(repo) {
  await ElMessageBox.confirm(`确定删除 ${repo.full_name} 的索引吗？`, '删除入库', { type: 'warning' })
  await store.deleteIndex(repo)
  ElMessage.success('已删除')
}

async function showLogs(repo) {
  logRepo.value = repo
  logsVisible.value = true
  try {
    logs.value = await api.syncLogs(repo.owner, repo.repo)
  } catch (error) {
    logs.value = []
    ElMessage.error(error.response?.data?.detail || '日志加载失败')
  }
}

async function importRepo() {
  const url = importUrl.value.trim()
  if (!url) {
    ElMessage.warning('请输入 GitHub 仓库链接')
    return
  }
  importing.value = true
  try {
    await api.importRepo(url)
    ElMessage.success('导入成功，正在入库')
    importVisible.value = false
    importUrl.value = ''
    await loadRepos(true)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(async () => {
  await loadRepos()
  activeRepo = store.repos.find((item) => item.index_status === 'indexing') || null
  if (activeRepo) {
    pollTimer = setInterval(pollIndexStatus, 3000)
  }
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2>GitHub 公开仓库</h2>
      <div class="filter-bar">
        <el-button @click="importVisible = true">导入公开仓库</el-button>
        <el-button type="primary" :loading="store.loadingRepos" @click="loadRepos(true)">刷新列表</el-button>
      </div>
    </div>
    <div class="import-hint">支持粘贴任意 github.com 公开仓库链接，例如 https://github.com/owner/repo</div>
    <el-table :data="store.repos" v-loading="store.loadingRepos" stripe>
      <el-table-column type="expand">
        <template #default="{ row }">
          <pre class="summary-text">{{ row.summary || '尚未生成摘要，重新入库后可见。' }}</pre>
        </template>
      </el-table-column>
      <el-table-column prop="full_name" label="仓库" min-width="220" />
      <el-table-column prop="default_branch" label="默认分支" width="120" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.index_status)">{{ statusText(row.index_status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近索引" width="180">
        <template #default="{ row }">{{ row.last_indexed_at || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="320">
        <template #default="{ row }">
          <el-button
            v-if="row.index_status === 'not_indexed' || row.index_status === 'failed'"
            type="danger"
            size="small"
            @click="index(row)"
          >
            入库
          </el-button>
          <el-button
            v-if="row.index_status === 'indexed'"
            size="small"
            @click="index(row)"
          >
            重新入库
          </el-button>
          <el-button
            v-if="row.index_status !== 'not_indexed'"
            type="danger"
            size="small"
            plain
            @click="remove(row)"
          >
            删除
          </el-button>
          <el-button size="small" @click="showLogs(row)">日志</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="logsVisible" :title="`${logRepo?.full_name || ''} 同步日志`" width="720px">
      <el-table :data="logs" size="small" max-height="420">
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column prop="action" label="动作" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
              {{ row.status === 'success' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="信息" min-width="260" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <el-dialog v-model="importVisible" title="导入公开仓库" width="520px">
      <el-input
        v-model="importUrl"
        placeholder="https://github.com/owner/repo"
        clearable
        @keyup.enter="importRepo"
      />
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="importRepo">导入并入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.import-hint {
  color: var(--text-muted);
  font-size: 12px;
  margin: -8px 0 12px;
}
</style>
