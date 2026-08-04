<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const providers = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'dashscope', label: '阿里云 DashScope' },
]

const form = reactive({
  provider: 'deepseek',
  model_name: '',
  api_key: '',
  base_url: '',
  is_active: true,
})
const saving = ref(false)

onMounted(async () => {
  const configs = await api.configs()
  const first = configs[0]
  if (first) {
    form.provider = first.provider
    form.model_name = first.model_name
    form.base_url = first.base_url
    form.is_active = first.is_active
  }
})

async function save() {
  saving.value = true
  try {
    await api.saveConfig(form)
    ElMessage.success('已保存')
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
          <el-select v-model="form.provider">
            <el-option v-for="item in providers" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.model_name" placeholder="例如 deepseek-chat 或 qwen-max" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="留空表示不修改" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="留空使用默认端点" />
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
