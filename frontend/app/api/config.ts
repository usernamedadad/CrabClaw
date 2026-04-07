import api from './index'

export interface AgentInfo {
  name: string
}

export interface LLMConfig {
  model_id: string
  api_key: string
  base_url: string
  temperature: number
  search_api_key: string
}

export interface PersonalityOption {
  id: string
  label: string
  description: string
}

export const configApi = {
  getAgentInfo: async () => api.get<AgentInfo>('/config/agent/info'),
  getLLM: async () => api.get<LLMConfig>('/config/llm'),
  listPersonalities: async () => api.get<{ items: PersonalityOption[] }>('/config/personalities'),
  updateLLM: async (llm: LLMConfig) => api.put<LLMConfig>('/config/llm', { llm })
}
