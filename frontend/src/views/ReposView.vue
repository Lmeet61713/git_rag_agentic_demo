<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAppStore } from '../stores/app'

const store = useAppStore()
let pollTimer = null
let activeRepo = null

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
      <el-button :loading="store.loadingRepos" @click="loadRepos(true)">刷新列表</el-button>
    </div>
    <el-table :data="store.repos" v-loading="store.loadingRepos" stripe>
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
      <el-table-column label="操作" width="240">
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
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
