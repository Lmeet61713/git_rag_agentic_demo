<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const catalog = ref([])
const form = reactive({
  provider: 'deepseek',
  model_name: '',
  api_key: '',
  base_url: '',
  is_active: true,
})
const saving = ref(false)

const providerOptions = computed(() =>
  catalog.value.map((item) => ({ value: item.provider, label: item.label })),
)
const currentProviderInfo = computed(
  () => catalog.value.find((item) => item.provider === form.provider) || null,
)
const modelOptions = computed(() => currentProviderInfo.value?.models || [])

async function loadModelData() {
  catalog.value = await api.modelCatalog()
  const configs = await api.configs()
  const first = configs[0]
  if (first) {
    form.provider = first.provider
    form.model_name = first.model_name
    form.base_url = first.base_url || currentProviderInfo.value?.base_url || ''
    form.is_active = first.is_active
  } else {
    form.base_url = currentProviderInfo.value?.base_url || ''
  }
}

onMounted(loadModelData)

function onProviderChange() {
  const info = currentProviderInfo.value
  if (!info) return
  form.base_url = info.base_url
  form.model_name = info.models.length ? info.models[0] : ''
  if (!info.requires_api_key) {
    form.api_key = ''
  }
}

async function save() {
  saving.value = true
  try {
    await api.saveConfig(form)
    ElMessage.success('已保存')
    form.api_key = ''
    await loadModelData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="toolbar"><h2>模型配置</h2></div>
    <el-card style="max-width: 640px">
      <el-form label-width="110px">
        <el-form-item label="服务商">
          <el-select v-model="form.provider" @change="onProviderChange">
            <el-option
              v-for="item in providerOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名">
          <el-select
            v-model="form.model_name"
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
          <el-input v-model="form.api_key" type="password" show-password placeholder="留空表示不修改" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="默认端点会自动填入" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>
