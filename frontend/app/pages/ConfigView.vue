<template>
  <section class="config-page page-shell">
    <header class="page-head">
      <div>
        <h2 class="brand-font">模型与 API 配置</h2>
        <p>修改后会在下一次请求时生效。</p>
      </div>
      <a-space>
        <a-button @click="load">刷新</a-button>
        <a-button type="primary" :loading="saving" @click="save">保存</a-button>
      </a-space>
    </header>

    <div class="surface form-shell">
      <a-form layout="vertical">
        <a-form-item label="model_id">
          <a-input v-model:value="form.model_id" placeholder="例如 gpt-4.1-mini" />
        </a-form-item>
        <a-form-item label="api_key">
          <a-input-password v-model:value="form.api_key" placeholder="API key" />
        </a-form-item>
        <a-form-item label="base_url">
          <a-input v-model:value="form.base_url" placeholder="OpenAI 兼容接口地址" />
        </a-form-item>
        <a-form-item label="temperature (0 ~ 2)">
          <a-input-number
            v-model:value="form.temperature"
            :min="0"
            :max="2"
            :step="0.05"
            style="width: 220px"
          />
        </a-form-item>
        <a-form-item label="search_api_key (SERPAPI_API)">
          <a-input-password v-model:value="form.search_api_key" placeholder="SerpAPI key" />
        </a-form-item>
      </a-form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { configApi } from '../api/config'

const saving = ref(false)
const form = reactive({
  model_id: '',
  api_key: '',
  base_url: '',
  temperature: 0.4,
  search_api_key: '',
})

async function load() {
  const llmRes = await configApi.getLLM()

  form.model_id = llmRes.data.model_id || ''
  form.api_key = llmRes.data.api_key || ''
  form.base_url = llmRes.data.base_url || ''
  form.temperature = Number.isFinite(llmRes.data.temperature) ? Number(llmRes.data.temperature) : 0.4
  form.search_api_key = llmRes.data.search_api_key || ''
}

async function save() {
  saving.value = true
  try {
    await configApi.updateLLM({ ...form })
    message.success('配置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.config-page {
  display: grid;
  gap: 14px;
  max-width: 920px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-head h2 {
  margin: 0;
}

.page-head p {
  margin: 4px 0 0;
  color: var(--muted);
}

.form-shell {
  padding: 18px;
}

@media (max-width: 900px) {
  .page-head {
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
