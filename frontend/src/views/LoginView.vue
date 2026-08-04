<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const route = useRoute()
const loading = ref(false)
const errorText = computed(() => {
  const code = route.query.error
  if (!code) return ''
  const messages = {
    invalid_state: '登录状态已失效，请重新从本页面发起 GitHub 登录。',
    oauth_code_expired: '授权码已过期或已使用，请重新点击 GitHub 登录。',
    oauth_config_error: 'GitHub OAuth 配置无效，请检查 Client ID 和 Client Secret。',
    oauth_callback_mismatch: 'GitHub 回调地址与 OAuth App 配置不一致，请检查 GITHUB_CALLBACK_URL。',
    oauth_failed: 'GitHub 授权未完成，请重试。',
  }
  return messages[code] || `登录失败：${code}`
})

async function login() {
  loading.value = true
  try {
    const data = await api.login()
    window.location.href = data.login_url
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '无法获取登录地址')
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2>MyAgentic</h2>
      <p>登录后可以将 GitHub 公开仓库索引到本地并进行 Agent 问答。</p>
      <el-alert
        v-if="errorText"
        type="error"
        :title="errorText"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-button type="primary" size="large" :loading="loading" @click="login">
        使用 GitHub 登录
      </el-button>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-card {
  width: 380px;
  text-align: center;
}
</style>
