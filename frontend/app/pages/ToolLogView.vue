<template>
  <section class="tool-log-page">
    <header class="page-head">
      <h1>工具日志</h1>
      <div class="actions">
        <button class="refresh-btn" type="button" @click="loadLogs">刷新</button>
      </div>
    </header>

    <div v-if="!logs.length" class="empty-state">暂无工具执行记录</div>

    <div v-else class="log-list">
      <div v-for="item in logs" :key="item.id" class="log-item">
        <div class="log-head">
          <strong>{{ item.userMessage }}</strong>
          <span class="log-time">{{ item.time }}</span>
        </div>
        <div class="log-tools">
          <div v-for="(tool, idx) in item.tools" :key="idx" class="tool-entry">
            <span class="tool-label">{{ tool }}</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionApi } from '../api/session'

interface LogItem {
  id: string
  userMessage: string
  tools: string[]
  time: string
}

const logs = ref<LogItem[]>([])

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

async function loadLogs() {
  try {
    const res = await sessionApi.list()
    const sessions = res.data.sessions || []
    const allLogs: LogItem[] = []

    for (const session of sessions) {
      try {
        const historyRes = await sessionApi.getHistory(session.id)
        const messages = historyRes.data.messages || []

        let currentUserMessage = ''
        let currentTools: string[] = []

        for (const msg of messages) {
          if (msg.role === 'user') {
            if (currentUserMessage && currentTools.length > 0) {
              allLogs.push({
                id: `${session.id}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
                userMessage: currentUserMessage,
                tools: [...currentTools],
                time: formatTime(session.updated_at)
              })
            }
            currentUserMessage = msg.content || ''
            currentTools = []
          } else if (msg.role === 'tool' && msg.content) {
            currentTools.push(msg.content)
          }
        }

        if (currentUserMessage && currentTools.length > 0) {
          allLogs.push({
            id: `${session.id}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
            userMessage: currentUserMessage,
            tools: [...currentTools],
            time: formatTime(session.updated_at)
          })
        }
      } catch {
        continue
      }
    }

    allLogs.reverse()
    logs.value = allLogs
  } catch {
    logs.value = []
  }
}

onMounted(() => {
  loadLogs()
})
</script>

<style scoped>
.tool-log-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 18px 24px;
  background: #f5f7fa;
  overflow: hidden;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.page-head h1 {
  margin: 0;
  font-size: 20px;
  color: #2e323a;
}

.actions {
  display: flex;
  gap: 8px;
}

.refresh-btn {
  border: 1px solid #d8dee9;
  background: #ffffff;
  color: #4b5563;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
}

.refresh-btn:hover {
  background: #f8fafc;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #8f97a6;
  font-size: 14px;
}

.log-list {
  flex: 1;
  overflow-y: auto;
  display: grid;
  gap: 12px;
}

.log-item {
  background: #ffffff;
  border: 1px solid #e7eaf0;
  border-radius: 12px;
  padding: 12px 14px;
}

.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.log-head strong {
  font-size: 14px;
  color: #2e323a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-time {
  font-size: 12px;
  color: #8f97a6;
  flex-shrink: 0;
}

.log-tools {
  display: grid;
  gap: 6px;
}

.tool-entry {
  font-size: 13px;
  color: #4b5563;
}
</style>
