<script setup>
import { FolderGit2, MessageSquareText, Settings, Brain, LogOut } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api/client'
import { useAppStore } from './stores/app'

const store = useAppStore()
const router = useRouter()
const route = useRoute()

const activeConfig = ref(null)
const catalog = ref([])
const modelDialogVisible = ref(false)
const modelForm = reactive({
  provider: 'deepseek',
  model_name: '',
  api_key: '',
  base_url: '',
  is_active: true,
})

const currentProviderInfo = computed(
  () => catalog.value.find((item) => item.provider === modelForm.provider) || null,
)
const modelOptions = computed(() => currentProviderInfo.value?.models || [])
const modelLabel = computed(() => {
  if (!activeConfig.value) return '未配置模型'
  const info = catalog.value.find((item) => item.provider === activeConfig.value.provider)
  const provider = info?.label || activeConfig.value.provider
  return `${provider} · ${activeConfig.value.model_name}`
})

async function loadModelStatus() {
  try {
    catalog.value = await api.modelCatalog()
    const configs = await api.configs()
    activeConfig.value = configs.find((item) => item.is_active) || configs[0] || null
  } catch {
    activeConfig.value = null
  }
}

function onProviderChange() {
  const info = currentProviderInfo.value
  if (!info) return
  modelForm.base_url = info.base_url
  modelForm.model_name = info.models.length ? info.models[0] : ''
  if (!info.requires_api_key) {
    modelForm.api_key = ''
  }
}

function openModelDialog() {
  const current = activeConfig.value
  if (current) {
    modelForm.provider = current.provider
    modelForm.model_name = current.model_name
    modelForm.base_url = current.base_url || currentProviderInfo.value?.base_url || ''
    modelForm.is_active = true
  } else {
    const first = catalog.value[0]
    if (first) {
      modelForm.provider = first.provider
      modelForm.base_url = first.base_url
      modelForm.model_name = first.models.length ? first.models[0] : ''
    }
    modelForm.is_active = true
  }
  modelForm.api_key = ''
  modelDialogVisible.value = true
}

async function applyModel() {
  await api.saveConfig({
    provider: modelForm.provider,
    model_name: modelForm.model_name,
    api_key: modelForm.api_key,
    base_url: modelForm.base_url,
    is_active: modelForm.is_active,
  })
  await loadModelStatus()
  modelDialogVisible.value = false
}

async function logout() {
  await store.logout()
  router.push('/login')
}

onMounted(loadModelStatus)
watch(
  () => route.path,
  () => loadModelStatus(),
)
</script>

<template>
  <el-container v-if="store.user" class="app-shell">
    <el-aside width="224px" class="app-aside">
      <div class="brand">
        <span class="brand-mark">M</span>
        <span>MyAgentic</span>
      </div>
      <nav class="app-nav">
        <router-link to="/repos" class="nav-item">
          <FolderGit2 :size="17" />
          <span>仓库</span>
        </router-link>
        <router-link to="/chat" class="nav-item">
          <MessageSquareText :size="17" />
          <span>聊天</span>
        </router-link>
        <router-link to="/config" class="nav-item">
          <Settings :size="17" />
          <span>模型配置</span>
        </router-link>
        <router-link to="/memory" class="nav-item">
          <Brain :size="17" />
          <span>记忆</span>
        </router-link>
      </nav>
      <div class="aside-foot">
        <div class="model-box">
          <div class="model-label">当前模型</div>
          <div class="model-value" :title="modelLabel">{{ modelLabel }}</div>
          <el-button size="small" text type="primary" @click="openModelDialog">切换</el-button>
        </div>
      </div>
    </el-aside>
    <el-container class="app-body">
      <el-header class="app-header">
        <div class="header-context">GitHub 公开仓库本地知识库</div>
        <div class="user-box">
          <el-avatar :size="30" :src="store.user.avatar_url" />
          <span class="username">{{ store.user.username }}</span>
          <el-tooltip content="退出登录" placement="bottom">
            <el-button text circle @click="logout">
              <LogOut :size="16" />
            </el-button>
          </el-tooltip>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
  <router-view v-else />

  <el-dialog v-model="modelDialogVisible" title="切换当前模型" width="480px">
    <el-form label-width="90px">
      <el-form-item label="服务商">
        <el-select v-model="modelForm.provider" @change="onProviderChange">
          <el-option
            v-for="item in catalog"
            :key="item.provider"
            :label="item.label"
            :value="item.provider"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="模型">
        <el-select
          v-model="modelForm.model_name"
          filterable
          allow-create
          default-first-option
          placeholder="选择或输入模型名"
        >
          <el-option
            v-for="model in modelOptions"
            :key="model"
            :label="model"
            :value="model"
          />
        </el-select>
      </el-form-item>
      <el-form-item v-if="currentProviderInfo?.requires_api_key !== false" label="API Key">
        <el-input
          v-model="modelForm.api_key"
          type="password"
          show-password
          placeholder="留空表示沿用已保存的 Key"
        />
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="modelForm.is_active" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="modelDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="applyModel">应用</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.app-aside {
  display: flex;
  flex-direction: column;
  background: #101820;
  color: #e6edf3;
  padding: 18px 14px;
  border-right: 1px solid #1f2937;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
  padding: 4px 8px 20px;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: #14b8a6;
  color: #082f2b;
  font-weight: 800;
}

.app-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 7px;
  color: #c7d1db;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-item:hover {
  background: #1f2937;
  color: #f8fafc;
}

.nav-item.router-link-exact-active {
  background: #14b8a6;
  color: #082f2b;
  font-weight: 600;
}

.aside-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #9aa7b5;
  font-size: 12px;
  padding: 10px 8px 0;
}

.model-box {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  background: #1f2937;
}

.model-label {
  color: #8b98a5;
  font-size: 11px;
}

.model-value {
  color: #f8fafc;
  font-size: 12px;
  line-height: 1.4;
  word-break: break-all;
}

.app-body {
  min-width: 0;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 58px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
}

.header-context {
  color: var(--text-muted);
  font-size: 13px;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 10px;
}

.username {
  font-size: 13px;
  color: var(--text);
}

.app-main {
  padding: 0;
}
</style>
