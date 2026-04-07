<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="toolbar-row">
      <button
        class="theme-btn"
        type="button"
        :aria-label="darkMode ? '切换浅色模式' : '切换深色模式'"
        :title="darkMode ? '切换浅色模式' : '切换深色模式'"
        @click="emit('toggle-theme')"
      >
        <span class="theme-glyph" aria-hidden="true">
          <svg v-if="!darkMode" viewBox="0 0 24 24" class="theme-icon" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 14.2A8.6 8.6 0 1 1 9.8 4A7.1 7.1 0 0 0 20 14.2Z" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" class="theme-icon" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="4.2" stroke="currentColor" stroke-width="2.2"/>
            <rect x="11" y="1.8" width="2" height="3" rx="0.5" fill="currentColor"/>
            <rect x="11" y="19.2" width="2" height="3" rx="0.5" fill="currentColor"/>
            <rect x="19.2" y="11" width="3" height="2" rx="0.5" fill="currentColor"/>
            <rect x="1.8" y="11" width="3" height="2" rx="0.5" fill="currentColor"/>
            <rect x="17.25" y="4.75" width="2" height="2" rx="0.4" transform="rotate(45 18.25 5.75)" fill="currentColor"/>
            <rect x="4.75" y="17.25" width="2" height="2" rx="0.4" transform="rotate(45 5.75 18.25)" fill="currentColor"/>
            <rect x="17.25" y="17.25" width="2" height="2" rx="0.4" transform="rotate(45 18.25 18.25)" fill="currentColor"/>
            <rect x="4.75" y="4.75" width="2" height="2" rx="0.4" transform="rotate(45 5.75 5.75)" fill="currentColor"/>
          </svg>
        </span>
      </button>
      <button
        class="collapse-btn"
        type="button"
        :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
        :title="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="emit('toggle')"
      >
        <span class="panel-icon" aria-hidden="true"></span>
      </button>
    </div>

    <nav class="nav-links">
      <RouterLink
        v-for="item in links"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :title="collapsed ? item.label : ''"
      >
        <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
        <span v-if="!collapsed">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <section v-if="!collapsed" class="session-switcher">
      <div class="session-head">
        <strong>历史会话</strong>
        <button class="session-refresh" type="button" title="刷新会话列表" @click="loadRecentSessions">↻</button>
      </div>

      <div class="session-list" :class="{ loading: sessionsLoading }">
        <button
          v-for="item in visibleSessions"
          :key="item.id"
          class="session-item"
          :class="{ active: item.id === currentSessionId }"
          type="button"
          @click="switchSession(item.id)"
          @contextmenu.prevent="openSessionContextMenu($event, item)"
        >
          <span class="session-title">{{ sessionTitle(item) }}</span>
          <small class="session-meta">{{ item.id === currentSessionId ? '当前对话' : formatSessionTime(item.updated_at) }}</small>
        </button>

        <div v-if="!sessionsLoading && !visibleSessions.length" class="session-empty">暂无历史会话</div>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="contextMenuOpen" class="session-context-overlay" @click="closeSessionContextMenu" @contextmenu.prevent>
        <div class="session-context-menu" :style="contextMenuStyle" @click.stop>
          <button class="session-context-item danger" type="button" @click="removeSessionFromContextMenu">删除会话</button>
        </div>
      </div>
    </Teleport>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import { sessionApi, type Session } from '../api/session'

const SESSION_KEY = 'crabclaw.session_id'
const SESSION_CHANGED_EVENT = 'crabclaw:session-changed'

withDefaults(
  defineProps<{
    collapsed?: boolean
    darkMode?: boolean
  }>(),
  {
    collapsed: false,
    darkMode: false
  }
)

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'toggle-theme'): void
}>()

const links = [
  { to: '/chat', label: '对话', icon: '◍' },
  { to: '/sessions', label: '会话管理', icon: '◷' },
  { to: '/skills', label: 'Skills', icon: '✦' },
  { to: '/memory', label: '记忆管理', icon: '◫' },
  { to: '/tool-log', label: '工具日志', icon: '⚒' },
  { to: '/config', label: '模型与API', icon: '⚙' }
]

const route = useRoute()
const router = useRouter()
const sessionsLoading = ref(false)
const recentSessions = ref<Session[]>([])
const currentSessionId = ref<string | null>(localStorage.getItem(SESSION_KEY))
const contextMenuOpen = ref(false)
const contextMenuX = ref(0)
const contextMenuY = ref(0)
const contextMenuSession = ref<Session | null>(null)

const visibleSessions = computed(() => recentSessions.value.slice(0, 12))
const contextMenuStyle = computed(() => ({
  left: `${contextMenuX.value}px`,
  top: `${contextMenuY.value}px`,
}))

function sessionTitle(item: Session): string {
  const title = (item.description || '').trim()
  if (title) {
    return title.length > 24 ? `${title.slice(0, 24)}...` : title
  }
  return item.id
}

function formatSessionTime(timestamp: number): string {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

async function loadRecentSessions() {
  sessionsLoading.value = true
  try {
    const res = await sessionApi.list()
    const sorted = [...(res.data.sessions || [])].sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))
    recentSessions.value = sorted
    currentSessionId.value = localStorage.getItem(SESSION_KEY)
  } catch {
    recentSessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

async function switchSession(sessionId: string) {
  closeSessionContextMenu()

  if (currentSessionId.value === sessionId) {
    return
  }

  currentSessionId.value = sessionId
  localStorage.setItem(SESSION_KEY, sessionId)
  window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId } }))
  if (route.path !== '/chat') {
    await router.push('/chat')
  }
}

function openSessionContextMenu(event: MouseEvent, item: Session) {
  const MENU_WIDTH = 148
  const MENU_HEIGHT = 46
  const PADDING = 8

  let x = event.clientX
  let y = event.clientY
  if (x + MENU_WIDTH > window.innerWidth - PADDING) {
    x = window.innerWidth - MENU_WIDTH - PADDING
  }
  if (y + MENU_HEIGHT > window.innerHeight - PADDING) {
    y = window.innerHeight - MENU_HEIGHT - PADDING
  }
  if (x < PADDING) x = PADDING
  if (y < PADDING) y = PADDING

  contextMenuSession.value = item
  contextMenuX.value = x
  contextMenuY.value = y
  contextMenuOpen.value = true
}

function closeSessionContextMenu() {
  contextMenuOpen.value = false
  contextMenuSession.value = null
}

async function deleteSessionFromHistory(item: Session) {
  closeSessionContextMenu()

  try {
    await sessionApi.delete(item.id)
    recentSessions.value = recentSessions.value.filter((session) => session.id !== item.id)

    if (currentSessionId.value === item.id) {
      const fallbackId = recentSessions.value[0]?.id || null
      currentSessionId.value = fallbackId

      if (fallbackId) {
        localStorage.setItem(SESSION_KEY, fallbackId)
      } else {
        localStorage.removeItem(SESSION_KEY)
      }

      window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: fallbackId || undefined } }))

      if (route.path !== '/chat') {
        await router.push('/chat')
      }
    }

    message.success('会话已删除')
  } catch {
    message.error('删除失败，请稍后重试')
  }
}

async function removeSessionFromContextMenu() {
  const target = contextMenuSession.value
  if (!target) {
    closeSessionContextMenu()
    return
  }
  await deleteSessionFromHistory(target)
}

function handleEscapeKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeSessionContextMenu()
  }
}

function handleSessionChanged(event: Event) {
  const detail = (event as CustomEvent<{ sessionId?: string }>).detail
  currentSessionId.value = detail?.sessionId || localStorage.getItem(SESSION_KEY)
}

watch(
  () => route.fullPath,
  () => {
    closeSessionContextMenu()
    loadRecentSessions()
  }
)

onMounted(() => {
  loadRecentSessions()
  window.addEventListener(SESSION_CHANGED_EVENT, handleSessionChanged as EventListener)
  window.addEventListener('keydown', handleEscapeKey)
})

onUnmounted(() => {
  window.removeEventListener(SESSION_CHANGED_EVENT, handleSessionChanged as EventListener)
  window.removeEventListener('keydown', handleEscapeKey)
})
</script>

<style scoped>
.sidebar {
  width: 100%;
  border-right: 1px solid var(--sidebar-line);
  background: var(--sidebar-bg);
  padding: 12px 10px;
  overflow: hidden;
}

.toolbar-row {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  min-height: 42px;
  padding: 4px 4px 6px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--sidebar-line);
  gap: 8px;
}

.theme-btn,
.collapse-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--sidebar-icon);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.theme-btn:hover,
.collapse-btn:hover {
  background: var(--sidebar-hover-bg);
}

.theme-glyph {
  width: 18px;
  height: 18px;
  display: inline-grid;
  place-items: center;
}

.theme-icon {
  width: 18px;
  height: 18px;
}

.theme-btn:focus-visible,
.collapse-btn:focus-visible {
  outline: 2px solid var(--sidebar-focus-ring);
  outline-offset: 2px;
}

.panel-icon {
  width: 16px;
  height: 16px;
  border: 1.6px solid var(--sidebar-icon);
  border-radius: 5px;
  display: inline-block;
  position: relative;
}

.panel-icon::after {
  content: '';
  position: absolute;
  left: 3px;
  top: 2px;
  bottom: 2px;
  width: 1.4px;
  background: var(--sidebar-icon);
  border-radius: 2px;
}

.nav-links {
  display: grid;
  gap: 8px;
  padding: 2px 2px 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--sidebar-text);
  border-radius: 10px;
  padding: 11px 12px;
  font-size: 15px;
  border: 1px solid transparent;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.nav-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  text-align: center;
  color: var(--sidebar-icon-soft);
  font-size: 12px;
}

.nav-item:hover {
  background: var(--sidebar-item-hover-bg);
  border-color: var(--sidebar-item-hover-border);
}

.nav-item.router-link-active {
  background: var(--sidebar-active-bg);
  color: var(--sidebar-active-text);
  border-color: var(--sidebar-active-border);
}

.nav-item.router-link-active .nav-icon {
  color: var(--sidebar-active-text);
}

.sidebar.collapsed {
  padding: 12px 8px;
}

.sidebar.collapsed .collapse-btn {
  width: 30px;
  height: 30px;
}

.sidebar.collapsed .nav-links {
  padding: 6px 0;
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 10px 8px;
  gap: 0;
}

.session-switcher {
  margin-top: 8px;
  border-top: 1px solid var(--sidebar-line);
  padding: 10px 2px 2px;
}

.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  color: var(--sidebar-icon-soft);
  font-size: 13px;
}

.session-refresh {
  width: 24px;
  height: 24px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--sidebar-icon-soft);
  cursor: pointer;
}

.session-refresh:hover {
  background: var(--sidebar-item-hover-bg);
  border-color: var(--sidebar-item-hover-border);
}

.session-list {
  display: grid;
  gap: 6px;
  max-height: calc(100vh - 270px);
  overflow-y: auto;
  padding-right: 2px;
}

.session-item {
  border: 1px solid transparent;
  background: transparent;
  border-radius: 10px;
  padding: 8px 10px;
  text-align: left;
  display: grid;
  gap: 2px;
  cursor: pointer;
}

.session-item:hover {
  background: var(--sidebar-item-hover-bg);
  border-color: var(--sidebar-item-hover-border);
}

.session-item.active {
  background: var(--sidebar-active-bg);
  border-color: var(--sidebar-active-border);
}

.session-title {
  color: var(--sidebar-text);
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  color: var(--sidebar-icon-soft);
  font-size: 12px;
}

.session-item.active .session-title,
.session-item.active .session-meta {
  color: var(--sidebar-active-text);
}

.session-item:focus-visible {
  outline: 2px solid var(--sidebar-focus-ring);
  outline-offset: 1px;
}

.session-context-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
}

.session-context-menu {
  position: fixed;
  min-width: 148px;
  padding: 6px;
  border-radius: 10px;
  border: 1px solid var(--sidebar-line);
  background: var(--sidebar-surface);
  box-shadow: 0 12px 28px rgba(8, 12, 20, 0.22);
}

.session-context-item {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  color: var(--sidebar-text);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.session-context-item:hover {
  background: var(--sidebar-item-hover-bg);
  border-color: var(--sidebar-item-hover-border);
}

.session-context-item.danger {
  color: #d65263;
}

.session-empty {
  padding: 8px 10px;
  color: var(--sidebar-icon-soft);
  font-size: 12px;
}

@media (max-width: 900px) {
  .sidebar {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid #e3e4e7;
    padding: 8px 10px;
  }

  .sidebar.collapsed {
    padding: 8px 10px;
  }

  .toolbar-row {
    padding: 2px 2px 8px;
    margin-bottom: 4px;
  }

  .collapse-btn {
    width: 30px;
    height: 30px;
  }

  .sidebar.collapsed .nav-item {
    justify-content: flex-start;
    gap: 12px;
    padding: 11px 12px;
  }

  .session-switcher {
    display: none;
  }

  .nav-links {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 2px 0 4px;
  }

  .nav-item {
    flex: 1 1 calc(50% - 8px);
    min-width: 132px;
  }
}
</style>
