import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useAppStore = defineStore('app', {
  state: () => ({
    user: null,
    repos: [],
    loadingRepos: false,
  }),
  actions: {
    async loadUser() {
      const data = await api.me()
      this.user = data.user
    },
    async logout() {
      await api.logout()
      this.user = null
    },
    async loadRepos(refresh = false) {
      this.loadingRepos = true
      try {
        this.repos = await api.repos(refresh)
      } finally {
        this.loadingRepos = false
      }
    },
    async indexRepo(repo) {
      await api.indexRepo(repo.owner, repo.repo)
      await this.loadRepos()
    },
    async deleteIndex(repo) {
      await api.deleteIndex(repo.owner, repo.repo)
      await this.loadRepos()
    },
  },
})
