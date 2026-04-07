<template>
  <section class="chat-page" :class="{ idle: !hasConversation, 'shift-motion': shiftMotion }">
    <header class="chat-brand-head">
      <img src="/crabclaw.png" alt="CrabClaw" class="chat-brand-logo" />
      <div class="chat-brand-text">
        <strong>CrabClaw</strong>
      </div>
    </header>

    <div class="idle-hero" v-if="!hasConversation">
      <h1 class="idle-title brand-font">你今天在想些什么？</h1>
    </div>

    <div class="messages" ref="messageContainer">
      <template v-for="item in messages" :key="item.id">
        <div v-if="item.kind === 'chat'" class="msg-row" :class="item.role">
          <img v-if="item.role === 'assistant'" src="/crabclaw.png" alt="assistant" class="avatar" />

          <div class="msg-body">
            <template v-if="item.role === 'assistant' && item.pending">
              <div class="typing-inline" aria-label="助手正在思考">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </template>
            <template v-else>
              <div class="bubble" :class="{ markdown: item.role === 'assistant' }">
                <div v-if="item.role === 'assistant'" class="md-content" v-html="renderAssistantMarkdown(item.content)"></div>
                <template v-else>{{ item.content }}</template>
              </div>
              <div class="meta">
                <span>{{ item.time }}</span>
                <button class="msg-action" type="button" @click="copyMessage(item)">复制</button>
                <button class="msg-action danger" type="button" @click="removeMessage(item)">删除</button>
              </div>
            </template>
          </div>

          <div v-if="item.role === 'user'" class="user-avatar" aria-hidden="true">👤</div>
        </div>
      </template>
    </div>

    <form class="composer" @submit.prevent="sendMessage">
      <div class="composer-wrap" ref="composerWrap">
        <div class="composer-inner">
          <button
            v-if="isSkillMode || selectedSkillId"
            class="skill-chip"
            type="button"
            @click="openSkillPicker"
            :disabled="streaming"
            :title="selectedSkillName ? `当前技能: ${selectedSkillName}` : '选择技能'"
          >
            # {{ selectedSkillName || '选择技能' }}
          </button>
          <input
            v-model="input"
            :disabled="streaming"
            class="composer-input"
            :placeholder="inputPlaceholder"
          />
          <button class="composer-send" type="submit" :disabled="streaming" aria-label="发送">➤</button>
        </div>

        <div v-if="skillPickerOpen" class="skill-picker-panel">
          <div class="skill-picker-head">选择技能</div>
          <div class="skill-picker-list">
            <button
              v-for="item in filteredSkills"
              :key="item.id"
              class="skill-picker-item"
              type="button"
              @click="chooseSkill(item.id)"
            >
              <span class="skill-picker-name">{{ item.name }}</span>
              <small class="skill-picker-desc">{{ item.description || item.id }}</small>
            </button>
            <div v-if="!skillsLoading && !filteredSkills.length" class="skill-picker-empty">暂无可选技能</div>
            <div v-if="skillsLoading" class="skill-picker-empty">技能列表加载中...</div>
          </div>
        </div>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { message as antdMessage } from 'ant-design-vue'
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { chatApi } from '../api/chat'
import { sessionApi, type ChatMessage } from '../api/session'
import { skillsApi, type SkillItem } from '../api/skills'

interface RenderMessage {
  id: string
  kind: 'chat' | 'tool'
  role: 'user' | 'assistant'
  content: string
  time: string
  toolState?: 'success' | 'error'
  pending?: boolean
}

const SESSION_KEY = 'crabclaw.session_id'
const SESSION_CHANGED_EVENT = 'crabclaw:session-changed'

const input = ref('')
const streaming = ref(false)
const currentSessionId = ref<string | null>(localStorage.getItem(SESSION_KEY))
const messages = ref<RenderMessage[]>([])
const messageContainer = ref<HTMLElement>()
const composerWrap = ref<HTMLElement>()
const shiftMotion = ref(false)
const hasConversation = computed(() => messages.value.length > 0)
const inputPlaceholder = '请输入...'
const skills = ref<SkillItem[]>([])
const skillsLoading = ref(false)
const skillPickerOpen = ref(false)
const selectedSkillId = ref<string | null>(null)
const isSkillMode = computed(() => /^\s*[#＃]/.test(input.value))
const selectedSkillName = computed(() => {
  if (!selectedSkillId.value) return ''
  const match = skills.value.find((item) => item.id === selectedSkillId.value)
  return match?.name || selectedSkillId.value
})
const filteredSkills = computed(() => skills.value)
let shiftTimer: ReturnType<typeof setTimeout> | null = null

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true
})

function nowText(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function renderAssistantMarkdown(content: string): string {
  const html = markdown.render(content || '')
  return DOMPurify.sanitize(html)
}

function pushChat(role: 'user' | 'assistant', content: string, id?: string) {
  if (!content?.trim()) return

  if (role === 'assistant') {
    const last = messages.value[messages.value.length - 1]
    if (last && last.kind === 'chat' && last.role === 'assistant' && !last.pending) {
      last.id = id || last.id
      last.content = content
      last.time = nowText()
      return
    }
  }

  messages.value.push({
    id: id || `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    kind: 'chat',
    role,
    content,
    time: nowText(),
    pending: false
  })
}



function briefError(content: string): string {
  const line = (content || '')
    .split('\n')
    .map((item) => item.trim())
    .find((item) => item.length > 0)
  if (!line) return '未知错误'
  return line.length > 80 ? `${line.slice(0, 80)}...` : line
}

function mapHistoryMessage(msg: ChatMessage) {
  if (msg.role === 'tool') return
  if (!msg.content) return
  pushChat(msg.role, msg.content, msg.id)
}

async function scrollToBottom() {
  await nextTick()
  const el = messageContainer.value
  if (el) el.scrollTop = el.scrollHeight
}

async function loadHistory() {
  if (!currentSessionId.value) return
  try {
    const res = await sessionApi.getHistory(currentSessionId.value)
    messages.value = []
    for (const msg of res.data.messages) {
      mapHistoryMessage(msg)
    }
    await scrollToBottom()
  } catch {
    // ignore history errors
  }
}

function handleSessionChanged(event: Event) {
  const detail = (event as CustomEvent<{ sessionId?: string }>).detail
  const nextSessionId = detail?.sessionId || localStorage.getItem(SESSION_KEY)
  if (!nextSessionId) {
    return
  }

  if (currentSessionId.value === nextSessionId) {
    return
  }

  currentSessionId.value = nextSessionId
  loadHistory()
}

async function createSession() {
  const res = await sessionApi.create()
  currentSessionId.value = res.data.session_id
  localStorage.setItem(SESSION_KEY, res.data.session_id)
  window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: res.data.session_id } }))
  messages.value = []
}

async function ensureSkillsLoaded() {
  if (skillsLoading.value) return
  skillsLoading.value = true
  try {
    const res = await skillsApi.list()
    skills.value = res.data.skills || []
  } catch {
    antdMessage.error('加载技能列表失败')
  } finally {
    skillsLoading.value = false
  }
}

async function openSkillPicker() {
  await ensureSkillsLoaded()
  skillPickerOpen.value = true
}

function chooseSkill(skillId: string) {
  selectedSkillId.value = skillId
  skillPickerOpen.value = false
  antdMessage.success(`已选择技能：${selectedSkillName.value || selectedSkillId.value}`)
}

function closeSkillPicker() {
  skillPickerOpen.value = false
}

function handleDocumentMouseDown(event: MouseEvent) {
  if (!skillPickerOpen.value) {
    return
  }

  const target = event.target as Node | null
  if (!target) {
    closeSkillPicker()
    return
  }

  if (composerWrap.value && !composerWrap.value.contains(target)) {
    closeSkillPicker()
  }
}

async function copyMessage(item: RenderMessage) {
  if (!item.content?.trim()) {
    antdMessage.warning('该消息没有可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(item.content)
    antdMessage.success('消息已复制')
  } catch {
    antdMessage.error('复制失败，请检查浏览器剪贴板权限')
  }
}

async function removeMessage(item: RenderMessage) {
  if (!currentSessionId.value) {
    antdMessage.error('当前会话不存在')
    return
  }

  const confirmed = window.confirm('确认删除这条消息吗？')
  if (!confirmed) return

  try {
    await sessionApi.deleteMessage(currentSessionId.value, item.id)
    messages.value = messages.value.filter((msg) => msg.id !== item.id)
    antdMessage.success('消息已删除')
  } catch {
    antdMessage.error('删除失败，可能是消息尚未写入会话历史')
  }
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || streaming.value) return

  const useSkillMode = /^\s*[#＃]/.test(text)
  if (useSkillMode && !selectedSkillId.value) {
    antdMessage.warning('请先选择技能后再发送 # 指令')
    await openSkillPicker()
    return
  }

  const skillIdForRequest = useSkillMode ? selectedSkillId.value : null

  closeSkillPicker()

  const shouldAnimateShift = !hasConversation.value
  if (shouldAnimateShift) {
    shiftMotion.value = true
    if (shiftTimer) {
      clearTimeout(shiftTimer)
    }
    shiftTimer = setTimeout(() => {
      shiftMotion.value = false
      shiftTimer = null
    }, 420)
  }

  pushChat('user', text)
  input.value = ''

  const assistant: RenderMessage = {
    id: `${Date.now()}-assistant`,
    kind: 'chat',
    role: 'assistant',
    content: '',
    time: nowText(),
    pending: true
  }
  messages.value.push(assistant)
  await scrollToBottom()

  streaming.value = true
  let streamFailed = false
  let streamDone = false
  try {
    await chatApi.sendMessageStream(
      text,
      currentSessionId.value,
      skillIdForRequest,
      (event) => {
        if (event.type === 'session' && event.session_id) {
          currentSessionId.value = event.session_id
          localStorage.setItem(SESSION_KEY, event.session_id)
          window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: event.session_id } }))
        }
        if (event.type === 'chunk') {
          if (event.content) {
            assistant.pending = false
            assistant.content += event.content
          }
          scrollToBottom()
        }
        if (event.type === 'done' && event.session_id) {
          streamDone = true
          currentSessionId.value = event.session_id
          localStorage.setItem(SESSION_KEY, event.session_id)
          window.dispatchEvent(new CustomEvent(SESSION_CHANGED_EVENT, { detail: { sessionId: event.session_id } }))
          if (!assistant.content.trim()) {
            messages.value = messages.value.filter((item) => item.id !== assistant.id)
          }
        }
        if (event.type === 'error') {
          streamFailed = true
          assistant.pending = false
          antdMessage.error('处理失败，请稍后重试')
          if (!assistant.content.trim()) {
            assistant.content = `处理失败：${briefError(event.error || '')}`
          }
        }
      }
    )
  } catch (error) {
    streamFailed = true
    assistant.pending = false
    antdMessage.error('处理失败，请稍后重试')
    if (!assistant.content.trim()) {
      assistant.content = `处理失败：${briefError((error as Error).message || '')}`
    }
  } finally {
    streaming.value = false
    if (streamDone || streamFailed) {
      await loadHistory()
    }
  }
}

onMounted(async () => {
  if (!currentSessionId.value) {
    await createSession()
  }
  window.addEventListener(SESSION_CHANGED_EVENT, handleSessionChanged as EventListener)
  document.addEventListener('mousedown', handleDocumentMouseDown)
  await ensureSkillsLoaded()
  await loadHistory()
})

watch(
  () => isSkillMode.value,
  async (enabled) => {
    if (!enabled) {
      selectedSkillId.value = null
      closeSkillPicker()
      return
    }
    if (!selectedSkillId.value) {
      await openSkillPicker()
    }
  }
)

onUnmounted(() => {
  window.removeEventListener(SESSION_CHANGED_EVENT, handleSessionChanged as EventListener)
  document.removeEventListener('mousedown', handleDocumentMouseDown)
  if (shiftTimer) {
    clearTimeout(shiftTimer)
    shiftTimer = null
  }
})
</script>

<style scoped>
.chat-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  overflow: hidden;
}

.chat-brand-head {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  margin: 0;
  padding: 12px 18px 8px;
  flex: 0 0 auto;
}

.chat-brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 999px;
  object-fit: cover;
}

.chat-brand-text strong {
  font-size: 22px;
  color: #2e323a;
  letter-spacing: 0.2px;
}

.idle-hero {
  display: flex;
  flex: 1;
  align-items: flex-end;
  justify-content: center;
  padding: 0 16px 28px;
}

.idle-title {
  margin: 0;
  font-size: clamp(30px, 3.6vw, 42px);
  font-weight: 700;
  color: #222831;
  letter-spacing: 0.4px;
}

.messages {
  flex: 1;
  overflow: auto;
  padding: 18px 24px 12px;
  opacity: 1;
}

.chat-page.idle .messages {
  flex: 0;
  height: 0;
  padding-top: 0;
  padding-bottom: 0;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
}

.msg-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: 16px auto;
  width: min(980px, 96%);
}

.msg-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 99px;
  object-fit: cover;
  margin-top: 2px;
}

.msg-body {
  max-width: min(72%, 760px);
}

.msg-row.user .msg-body {
  max-width: min(54%, 560px);
}

.bubble {
  background: #fafafb;
  border: 1px solid #d8dbe0;
  border-radius: 14px;
  padding: 13px 16px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: #3c414a;
  box-shadow: 0 2px 8px rgba(24, 30, 38, 0.05);
  position: relative;
}

.bubble.markdown {
  white-space: normal;
}

.typing-inline {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 2px;
}

.typing-inline span {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #8f97a6;
  animation: dot-bounce 1s infinite ease-in-out;
}

.typing-inline span:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-inline span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes dot-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

.md-content :deep(p) {
  margin: 0 0 10px;
}

.md-content :deep(p:last-child) {
  margin-bottom: 0;
}

.md-content :deep(strong) {
  font-weight: 700;
}

.md-content :deep(ul),
.md-content :deep(ol) {
  margin: 0;
  padding-left: 22px;
}

.md-content :deep(code) {
  background: #eef1f5;
  border-radius: 6px;
  padding: 1px 6px;
  font-size: 12px;
}

.md-content :deep(pre) {
  margin: 8px 0;
  padding: 10px 12px;
  background: #f2f4f7;
  border-radius: 10px;
  overflow-x: auto;
}

.md-content :deep(pre code) {
  background: transparent;
  padding: 0;
}

.msg-row.user .bubble {
  background: #ffffff;
  border-color: #d8dbe0;
}

.meta {
  margin-top: 7px;
  font-size: 12px;
  color: #7f8792;
  display: flex;
  align-items: center;
  gap: 10px;
}

.msg-action {
  border: none;
  background: transparent;
  color: #6f7785;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.msg-action:hover {
  color: #4d5563;
}

.msg-action.danger:hover {
  color: #d4494f;
}

.user-avatar {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  border: 1px solid #d7dbe1;
  background: #f6f7f9;
  display: grid;
  place-items: center;
  font-size: 16px;
  margin-top: 2px;
}

.composer {
  border-top: 1px solid #e7eaf0;
  background: #ffffff;
  padding: 12px 18px 18px;
}

.composer-wrap {
  width: min(784px, 100%);
  margin: 0 auto;
  position: relative;
}

.chat-page.idle .composer {
  border-top-color: transparent;
  background: transparent;
  padding: 0 18px 40vh;
  transform: translateY(-14vh);
}

.chat-page.idle .idle-hero {
  transform: translateY(-14vh);
}

.composer-inner {
  width: 100%;
  margin: 0;
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  align-items: center;
  border: 1px solid transparent;
  background:
    linear-gradient(180deg, #f7f8fa 0%, #f2f4f7 100%) padding-box,
    linear-gradient(120deg, rgba(123, 169, 255, 0.62), rgba(132, 232, 255, 0.58), rgba(156, 196, 255, 0.62))
      border-box;
  border-radius: 999px;
  padding: 6px 8px;
  box-shadow: 0 10px 24px rgba(28, 35, 46, 0.08), 0 0 0 1px rgba(139, 184, 255, 0.2);
}

.skill-chip {
  flex: 0 0 auto;
  border: 1px solid #e4d3d8;
  background: #fdf3f5;
  color: #9d4f5b;
  border-radius: 999px;
  padding: 0 12px;
  height: 36px;
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  font-size: 13px;
}

.skill-chip:hover {
  background: #f9e8ec;
}

.skill-picker-panel {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 10px);
  border: 1px solid var(--line);
  background: var(--sidebar-surface);
  border-radius: 12px;
  box-shadow: 0 16px 32px rgba(17, 23, 35, 0.18);
  overflow: hidden;
  z-index: 20;
}

.skill-picker-head {
  padding: 10px 12px;
  font-size: 13px;
  color: var(--muted);
  border-bottom: 1px solid var(--line);
}

.skill-picker-list {
  max-height: 220px;
  overflow-y: auto;
  display: grid;
}

.skill-picker-item {
  border: none;
  border-bottom: 1px solid var(--line);
  background: transparent;
  text-align: left;
  padding: 9px 12px;
  cursor: pointer;
  display: grid;
  gap: 2px;
}

.skill-picker-item:last-child {
  border-bottom: none;
}

.skill-picker-item:hover {
  background: var(--sidebar-item-hover-bg);
}

.skill-picker-name {
  font-size: 14px;
  color: var(--text);
}

.skill-picker-desc {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-picker-empty {
  padding: 12px;
  color: var(--muted);
  font-size: 12px;
}

.skill-tip {
  margin-bottom: 10px;
  color: #5b616f;
}

.skill-empty {
  margin-top: 10px;
  color: #8f95a1;
}

.chat-page.idle .composer-inner {
  box-shadow: 0 16px 36px rgba(28, 35, 46, 0.11);
}

.chat-page.shift-motion .messages {
  transition: opacity 0.24s ease, padding 0.24s ease;
}

.chat-page.shift-motion .composer {
  transition: padding 0.28s ease, border-color 0.28s ease, background-color 0.28s ease;
}

.chat-page.shift-motion .composer-inner {
  transition: box-shadow 0.24s ease;
}

.composer-input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  background: transparent;
  border-radius: 12px;
  height: 46px;
  padding: 0 8px;
  font-size: 16px;
  outline: none;
  color: #313744;
}

.composer-input:focus {
  background: rgba(255, 255, 255, 0.36);
}

.composer-send {
  flex: 0 0 auto;
  width: 40px;
  height: 40px;
  border-radius: 999px;
  border: 1px solid #cfd5df;
  background: #ffffff;
  color: #2f3745;
  font-size: 16px;
  cursor: pointer;
}

.composer-send:not(:disabled):hover {
  background: #eef1f5;
}

.composer-send:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .idle-title {
    font-size: clamp(26px, 8vw, 34px);
  }

  .messages {
    padding: 16px 12px 8px;
  }

  .chat-brand-head {
    width: 100%;
    padding: 12px 10px 4px;
  }

  .msg-row {
    width: 100%;
  }

  .msg-row.user .msg-body,
  .msg-body {
    max-width: 88%;
  }

  .composer {
    padding: 10px 10px 12px;
  }

  .chat-page.idle .composer {
    padding: 0 10px 34vh;
    transform: translateY(-10vh);
  }

  .chat-page.idle .idle-hero {
    transform: translateY(-10vh);
  }
}
</style>
