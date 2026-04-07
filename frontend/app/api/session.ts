import api from './index'

export interface Session {
  id: string
  created_at: number
  updated_at: number
  description?: string
}

export interface SessionCreatePayload {
  summarize_old?: boolean
  old_session_id?: string
  session_id?: string
  description?: string
}

export interface ToolCallFunction {
  name: string
  arguments: string
}

export interface ToolCall {
  id: string
  type: 'function'
  function: ToolCallFunction
}

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'tool'
  content?: string
  tool_calls?: ToolCall[]
  tool_call_id?: string
}

export interface SessionHistory {
  session_id: string
  messages: ChatMessage[]
}

export const sessionApi = {
  list: async () => api.get<{ sessions: Session[] }>('/session/list'),
  create: async (payload: SessionCreatePayload = {}) => api.post<{ session_id: string; summary_file?: string }>('/session/create', payload),
  delete: async (id: string) => api.delete(`/session/${id}`),
  getHistory: async (id: string) => api.get<SessionHistory>(`/session/${id}/history`),
  deleteMessage: async (sessionId: string, messageId: string) => api.delete(`/session/${sessionId}/messages/${messageId}`)
}
