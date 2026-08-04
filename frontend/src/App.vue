<script setup>
import { useRouter } from 'vue-router'
import { useAppStore } from './stores/app'

const store = useAppStore()
const router = useRouter()

async function logout() {
  await store.logout()
  router.push('/login')
}
</script>

<template>
  <el-container v-if="store.user">
    <el-header class="app-header">
      <div class="brand">MyAgentic</div>
      <el-menu mode="horizontal" :default-active="$route.path" router>
        <el-menu-item index="/repos">仓库</el-menu-item>
        <el-menu-item index="/chat">聊天</el-menu-item>
        <el-menu-item index="/config">模型配置</el-menu-item>
      </el-menu>
      <div class="user-box">
        <el-avatar :size="28" :src="store.user.avatar_url" />
        <span>{{ store.user.username }}</span>
        <el-button text type="danger" @click="logout">退出</el-button>
      </div>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
  <router-view v-else />
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.brand {
  font-weight: 700;
  font-size: 18px;
}

.user-box {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
