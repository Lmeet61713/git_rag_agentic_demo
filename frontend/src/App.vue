<script setup>
import { Boxes, FolderGit2, MessageSquareText, Settings, Brain, LogOut } from 'lucide-vue-next'
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
    <el-header class="app-header">
      <div class="header-left">
        <div class="brand">
          <span class="brand-mark"><Boxes :size="16" /></span>
          <span class="brand-name">MyAgentic</span>
        </div>
        <nav class="app-nav">
          <router-link to="/repos" class="nav-item">
            <FolderGit2 :size="16" />
            <span>仓库</span>
          </router-link>
          <router-link to="/chat" class="nav-item">
            <MessageSquareText :size="16" />
            <span>聊天</span>
          </router-link>
          <router-link to="/config" class="nav-item">
            <Settings :size="16" />
            <span>模型配置</span>
          </router-link>
          <router-link to="/memory" class="nav-item">
            <Brain :size="16" />
            <span>记忆</span>
          </router-link>
        </nav>
      </div>
      <div class="header-right">
        <button class="model-chip" type="button" @click="openModelDialog">
          <span class="model-label">当前模型</span>
          <span class="model-value" :title="modelLabel">{{ modelLabel }}</span>
        </button>
        <div class="user-box">
          <el-avatar :size="28" :src="store.user.avatar_url" />
          <span class="username">{{ store.user.username }}</span>
          <el-tooltip content="退出登录" placement="bottom">
            <el-button text circle @click="logout">
              <LogOut :size="15" />
            </el-button>
          </el-tooltip>
        </div>
      </div>
    </el-header>
    <el-main class="app-main">
      <router-view />
    </el-main>
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

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
  min-width: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, #0f766e, #14b8a6);
  color: #ffffff;
}

.app-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 7px;
  color: var(--text-muted);
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-item:hover {
  background: var(--surface-muted);
  color: var(--text);
}

.nav-item.router-link-exact-active {
  background: var(--accent-weak);
  color: var(--accent-strong);
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.model-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-muted);
  cursor: pointer;
  text-align: left;
}

.model-label {
  font-size: 10px;
  color: var(--text-muted);
}

.model-value {
  font-size: 12px;
  color: var(--text);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
