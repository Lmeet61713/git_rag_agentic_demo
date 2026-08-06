import { createRouter, createWebHistory } from 'vue-router'
import { useAppStore } from '../stores/app'

import LoginView from '../views/LoginView.vue'
import ReposView from '../views/ReposView.vue'
import ChatView from '../views/ChatView.vue'
import ConfigView from '../views/ConfigView.vue'
import MemoryView from '../views/MemoryView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/repos' },
    { path: '/login', component: LoginView },
    { path: '/repos', component: ReposView },
    { path: '/chat', component: ChatView },
    { path: '/config', component: ConfigView },
    { path: '/memory', component: MemoryView },
  ],
})

router.beforeEach(async (to) => {
  const store = useAppStore()
  if (!store.user) {
    await store.loadUser()
  }
  if (!store.user && to.path !== '/login') {
    return '/login'
  }
  if (store.user && to.path === '/login') {
    return '/repos'
  }
})

export default router
