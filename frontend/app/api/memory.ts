import api from './index'

export interface MemoryFile {
  name: string
  type: 'daily' | 'longterm'
  size: number
  updated_at: number
}

export const memoryApi = {
  files: async () => api.get<{ files: MemoryFile[] }>('/memory/files'),
  content: async (filename: string) => api.get<{ filename: string; content: string }>('/memory/content', {
    params: { filename }
  }),
  update: async (filename: string, content: string) =>
    api.put<{ filename: string; content: string; status: string }>('/memory/content', { filename, content }),
  reset: async (filename: string) =>
    api.post<{ filename: string; content: string; status: string }>('/memory/reset', { filename })
}
