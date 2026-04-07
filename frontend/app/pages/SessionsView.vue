<template>
  <section class="page-shell sessions-page">
    <header class="page-head">
      <h2 class="brand-font">会话管理</h2>
      <a-button type="primary" @click="openCreate">创建会话</a-button>
    </header>

    <div class="surface table-wrap">
      <a-table :data-source="sessions" :pagination="false" row-key="id" size="middle">
        <a-table-column title="会话 ID" data-index="id" key="id" />
        <a-table-column title="会话描述" key="description">
          <template #default="{ record }">
            {{ record.description || '（未填写）' }}
          </template>
        </a-table-column>
        <a-table-column title="创建时间" key="created_at">
          <template #default="{ record }">
            {{ new Date(record.created_at * 1000).toLocaleString() }}
          </template>
        </a-table-column>
        <a-table-column title="操作" key="actions" width="280">
          <template #default="{ record }">
            <a-space :size="8" wrap>
              <a-button
                size="small"
                :type="record.id === currentSessionId ? 'primary' : 'default'"
                @click="select(record.id)"
              >
                {{ record.id === currentSessionId ? '当前对话' : '切换' }}
              </a-button>
              <a-popconfirm title="确认删除该会话？" @confirm="remove(record.id)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </a-table-column>
      </a-table>
    </div>

    <a-modal
      v-model:open="createOpen"
      title="创建会话"
      ok-text="创建"
      cancel-text="取消"
      :confirm-loading="creating"
      @ok="submitCreate"
    >
      <a-form layout="vertical">
        <a-form-item label="会话 ID" required>
          <a-input
            v-model:value="createForm.session_id"
            placeholder="例如: crabclaw-task-001"
            :maxlength="64"
          />
        </a-form-item>
        <a-form-item label="会话描述（可选）">
          <a-textarea
            v-model:value="createForm.description"
            placeholder="例如: 需求评审会话"
            :maxlength="200"
            :auto-size="{ minRows: 2, maxRows: 4 }"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { sessionApi, type Session } from '../api/session'

const SESSION_KEY = 'crabclaw.session_id'
const SESSION_CHANGED_EVENT = 'crabclaw:session-changed'
const sessions = ref<Session[]>([])
const currentSessionId = ref<string | null>(localStorage.getItem(SESSION_KEY))
const createOpen = ref(false)
const creating = ref(false)
const createForm = reactive({
  session_id: '',
  description: ''
})

async function load() {
  const res = await sessionApi.list()
  sessions.value = res.data.sessions
  if (currentSessionId.value && !sessions.value.some((item) => item.id === currentSessionId.value)) {
    currentSessionId.value = null
    localStorage.removeItem(SESSION_KEY)
    window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: undefined } }))
  }
}

function handleSessionChanged(event: Event) {
  const detail = (event as CustomEvent<{ sessionId?: string }>).detail
  currentSessionId.value = detail?.sessionId || localStorage.getItem(SESSION_KEY)
}

function openCreate() {
  createForm.session_id = ''
  createForm.description = ''
  createOpen.value = true
}

function errorDetail(error: unknown): string {
  const maybe = error as { response?: { data?: { detail?: string } }; message?: string }
  return maybe?.response?.data?.detail || maybe?.message || '操作失败'
}

async function submitCreate() {
  const sid = createForm.session_id.trim()
  const description = createForm.description.trim()
  if (!sid) {
    message.error('会话 ID 为必填项')
    return
  }

  creating.value = true
  try {
    const res = await sessionApi.create({
      session_id: sid,
      description: description || undefined
    })
    currentSessionId.value = res.data.session_id
    localStorage.setItem(SESSION_KEY, res.data.session_id)
    window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: res.data.session_id } }))
    message.success(`已创建会话 ${res.data.session_id}`)
    createOpen.value = false
    await load()
  } catch (error) {
    message.error(errorDetail(error))
  } finally {
    creating.value = false
  }
}

function select(id: string) {
  currentSessionId.value = id
  localStorage.setItem(SESSION_KEY, id)
  window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: id } }))
  message.success(`已切换会话 ${id}`)
}

async function remove(id: string) {
  await sessionApi.delete(id)
  if (localStorage.getItem(SESSION_KEY) === id) {
    const fallbackId = sessions.value.find((item) => item.id !== id)?.id || null
    currentSessionId.value = fallbackId
    if (fallbackId) {
      localStorage.setItem(SESSION_KEY, fallbackId)
    } else {
      localStorage.removeItem(SESSION_KEY)
    }
    window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: fallbackId || undefined } }))
  }
  message.success('已删除会话')
  await load()
}

onMounted(() => {
  load()
  window.addEventListener(SESSION_CHANGED_EVENT, handleSessionChanged as EventListener)
})

onUnmounted(() => {
  window.removeEventListener(SESSION_CHANGED_EVENT, handleSessionChanged as EventListener)
})
</script>

<style scoped>
.sessions-page {
  display: grid;
  gap: 16px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-head h2 {
  margin: 0;
}

.table-wrap {
  padding: 10px;
}

:deep(.ant-table-wrapper .ant-table) {
  border-radius: 10px;
}

@media (max-width: 900px) {
  .table-wrap {
    padding: 4px;
  }
}
</style>
