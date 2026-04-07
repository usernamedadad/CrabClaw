<template>
  <section class="memory-page page-shell">
    <header class="page-head">
      <div>
        <h2 class="brand-font">记忆管理</h2>
        <p>可编辑长期记忆与每日记忆文件，支持重置。</p>
      </div>
      <a-space>
        <a-button @click="loadFiles">刷新列表</a-button>
        <a-button type="primary" :disabled="!selectedFilename" :loading="saving" @click="saveCurrent">
          保存修改
        </a-button>
        <a-popconfirm
          title="确认重置当前文件吗？"
          description="此操作会覆盖当前文件内容。"
          ok-text="重置"
          cancel-text="取消"
          @confirm="resetCurrent"
        >
          <a-button danger ghost :disabled="!selectedFilename" :loading="resetting">重置文件</a-button>
        </a-popconfirm>
      </a-space>
    </header>

    <div class="memory-grid">
      <aside class="surface memory-list">
        <h3>文件列表</h3>
        <a-list :data-source="files" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <button class="file-btn" :class="{ active: item.name === selectedFilename }" @click="open(item.name)">
                <span class="name">{{ item.name }}</span>
                <small>{{ item.type }}</small>
              </button>
            </a-list-item>
          </template>
        </a-list>
      </aside>

      <article class="surface memory-content">
        <h3>{{ selectedFilename ? `编辑 ${selectedFilename}` : '内容编辑' }}</h3>
        <a-textarea
          v-model:value="editorContent"
          class="editor"
          :disabled="!selectedFilename"
          :auto-size="{ minRows: 18, maxRows: 34 }"
          placeholder="请选择左侧文件后进行编辑。"
        />
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { memoryApi, type MemoryFile } from '../api/memory'

const files = ref<MemoryFile[]>([])
const selectedFilename = ref('')
const editorContent = ref('')
const saving = ref(false)
const resetting = ref(false)

async function loadFiles() {
  const res = await memoryApi.files()
  files.value = res.data.files

  if (selectedFilename.value && !files.value.some((item) => item.name === selectedFilename.value)) {
    selectedFilename.value = ''
    editorContent.value = ''
  }
}

async function open(filename: string) {
  const res = await memoryApi.content(filename)
  selectedFilename.value = filename
  editorContent.value = res.data.content
}

async function saveCurrent() {
  if (!selectedFilename.value) {
    message.warning('请先选择一个记忆文件')
    return
  }

  saving.value = true
  try {
    await memoryApi.update(selectedFilename.value, editorContent.value)
    message.success('记忆文件已保存')
    await loadFiles()
  } finally {
    saving.value = false
  }
}

async function resetCurrent() {
  if (!selectedFilename.value) {
    return
  }

  resetting.value = true
  try {
    const res = await memoryApi.reset(selectedFilename.value)
    editorContent.value = res.data.content
    message.success('记忆文件已重置')
    await loadFiles()
  } finally {
    resetting.value = false
  }
}

onMounted(loadFiles)
</script>

<style scoped>
.memory-page {
  display: grid;
  gap: 14px;
}

.page-head h2 {
  margin: 0;
}

.page-head p {
  margin: 4px 0 0;
  color: var(--muted);
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.memory-grid {
  display: grid;
  grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
  gap: 14px;
  min-height: calc(100vh - 220px);
}

.memory-list,
.memory-content {
  padding: 16px;
  overflow: auto;
}

.memory-list h3,
.memory-content h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.file-btn {
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  background: #ffffff;
  border-radius: 10px;
  padding: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.file-btn .name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-btn:hover {
  border-color: #d7dbe0;
}

.file-btn.active {
  border-color: #e9c3c8;
  background: #f9ecee;
}

.editor {
  width: 100%;
}

:deep(.editor textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
  line-height: 1.64;
}

@media (max-width: 900px) {
  .page-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .memory-grid {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}
</style>
