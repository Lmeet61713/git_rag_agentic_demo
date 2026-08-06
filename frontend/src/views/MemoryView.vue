<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'

const memories = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const filter = reactive({ project_id: '', type: '' })
const form = reactive({ content: '', project_id: '', session_id: '', type: 'long_term' })

const typeOptions = [
  { value: 'long_term', label: '长期记忆' },
  { value: 'short_term', label: '短期记忆' },
]

async function load() {
  loading.value = true
  try {
    const params = {}
    if (filter.project_id) params.project_id = filter.project_id
    if (filter.type) params.type = filter.type
    memories.value = await api.memories(params)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '记忆列表加载失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.content = ''
  form.project_id = ''
  form.session_id = ''
  form.type = 'long_term'
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.content = row.content
  form.project_id = row.project_id || ''
  form.session_id = row.session_id || ''
  form.type = row.type
  dialogVisible.value = true
}

async function save() {
  if (!form.content.trim()) {
    ElMessage.warning('请填写记忆内容')
    return
  }
  const payload = {
    content: form.content.trim(),
    project_id: form.project_id || null,
    session_id: form.session_id ? Number(form.session_id) : null,
    type: form.type,
  }
  try {
    if (editingId.value) {
      await api.updateMemory(editingId.value, payload)
    } else {
      await api.createMemory(payload)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除这条${row.type === 'long_term' ? '长期' : '短期'}记忆吗？`, '删除记忆', {
    type: 'warning',
  })
  await api.deleteMemory(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <h2>记忆管理</h2>
      <div class="filter-bar">
        <el-input
          v-model="filter.project_id"
          placeholder="项目，如 owner/repo"
          clearable
          style="width: 220px"
          @keyup.enter="load"
        />
        <el-select v-model="filter.type" placeholder="全部类型" clearable style="width: 140px">
          <el-option
            v-for="item in typeOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-button @click="load">查询</el-button>
        <el-button type="primary" @click="openCreate">新建记忆</el-button>
      </div>
    </div>

    <el-table :data="memories" v-loading="loading" stripe>
      <el-table-column prop="content" label="内容" min-width="320" show-overflow-tooltip />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag :type="row.type === 'long_term' ? 'primary' : 'info'" effect="plain">
            {{ row.type === 'long_term' ? '长期' : '短期' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="project_id" label="项目" width="180">
        <template #default="{ row }">{{ row.project_id || '-' }}</template>
      </el-table-column>
      <el-table-column label="会话" width="80">
        <template #default="{ row }">{{ row.session_id || '-' }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ row.updated_at || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑记忆' : '新建记忆'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="4" placeholder="例如：用户偏好 Python，常在本地运行 FastAPI" />
        </el-form-item>
        <el-form-item label="项目">
          <el-input v-model="form.project_id" placeholder="可选，格式 owner/repo" />
        </el-form-item>
        <el-form-item label="会话 ID">
          <el-input v-model="form.session_id" placeholder="可选" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type">
            <el-option
              v-for="item in typeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  gap: 8px;
}
</style>
