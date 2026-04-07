<template>
  <section class="skills-page page-shell">
    <header class="page-head">
      <div>
        <h2 class="brand-font">Skills 管理</h2>
        <p>管理本地技能目录，支持本地导入、URL 下载和删除。</p>
      </div>
      <a-button @click="loadSkills" :loading="loading">刷新</a-button>
    </header>

    <div class="skills-grid">
      <article class="surface skill-import">
        <h3>添加技能</h3>

        <div class="block">
          <label>本地路径导入</label>
          <a-input v-model:value="localPath" placeholder="例如 D:/downloads/pptx 或 D:/downloads/pptx/SKILL.md" />
          <a-button type="primary" :loading="installingLocal" @click="installLocal">导入本地技能</a-button>
        </div>

        <div class="block">
          <label>URL 下载导入</label>
          <a-input v-model:value="downloadUrl" placeholder="请输入可访问的 skill markdown 或 zip 地址" />
          <a-button type="primary" ghost :loading="installingUrl" @click="installByUrl">下载并导入</a-button>
        </div>
      </article>

      <article class="surface skill-list">
        <h3>已安装技能</h3>

        <a-empty v-if="!loading && !skills.length" description="还没有安装技能" />

        <a-list v-else :data-source="skills" item-layout="vertical">
          <template #renderItem="{ item }">
            <a-list-item>
              <div class="skill-row">
                <div class="info">
                  <strong>{{ item.name }}</strong>
                  <small>ID: {{ item.id }}</small>
                  <p>{{ item.description || '暂无描述' }}</p>
                </div>
                <a-popconfirm
                  title="确认删除此技能吗？"
                  ok-text="删除"
                  cancel-text="取消"
                  @confirm="removeSkill(item.id)"
                >
                  <a-button danger ghost>删除</a-button>
                </a-popconfirm>
              </div>
            </a-list-item>
          </template>
        </a-list>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { skillsApi, type SkillItem } from '../api/skills'

const skills = ref<SkillItem[]>([])
const loading = ref(false)
const installingLocal = ref(false)
const installingUrl = ref(false)
const localPath = ref('')
const downloadUrl = ref('')

function extractErrorMessage(error: unknown, fallback: string): string {
  const maybe = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
  return maybe?.response?.data?.detail || maybe?.response?.data?.message || maybe?.message || fallback
}

async function loadSkills() {
  loading.value = true
  try {
    const res = await skillsApi.list()
    skills.value = res.data.skills || []
  } catch (error) {
    message.error(extractErrorMessage(error, '加载技能列表失败'))
  } finally {
    loading.value = false
  }
}

async function installLocal() {
  const path = localPath.value.trim()
  if (!path) {
    message.warning('请输入本地路径')
    return
  }

  installingLocal.value = true
  try {
    const res = await skillsApi.installLocal(path)
    message.success(res.data.message || '本地技能导入成功')
    localPath.value = ''
    await loadSkills()
  } catch (error) {
    message.error(extractErrorMessage(error, '本地导入失败'))
  } finally {
    installingLocal.value = false
  }
}

async function installByUrl() {
  const url = downloadUrl.value.trim()
  if (!url) {
    message.warning('请输入下载地址')
    return
  }

  installingUrl.value = true
  try {
    const res = await skillsApi.installUrl(url)
    message.success(res.data.message || '下载导入成功')
    downloadUrl.value = ''
    await loadSkills()
  } catch (error) {
    message.error(extractErrorMessage(error, '下载导入失败'))
  } finally {
    installingUrl.value = false
  }
}

async function removeSkill(skillId: string) {
  try {
    await skillsApi.remove(skillId)
    message.success('技能已删除')
    await loadSkills()
  } catch (error) {
    message.error(extractErrorMessage(error, '删除失败'))
  }
}

onMounted(loadSkills)
</script>

<style scoped>
.skills-page {
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

.skills-grid {
  display: grid;
  grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
  gap: 14px;
  min-height: calc(100vh - 220px);
}

.skill-import,
.skill-list {
  padding: 16px;
  overflow: auto;
}

.skill-import h3,
.skill-list h3 {
  margin: 0 0 12px;
  font-size: 16px;
}

.block {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
}

.block label {
  color: #4a4f59;
  font-size: 13px;
}

.skill-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.info {
  display: grid;
  gap: 4px;
}

.info small {
  color: #7a8190;
}

.info p {
  margin: 0;
  color: #4b5260;
}

@media (max-width: 900px) {
  .page-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .skills-grid {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}
</style>
