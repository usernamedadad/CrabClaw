import api from './index'

export interface SkillItem {
  id: string
  name: string
  description: string
  path: string
  entry: string
  updated_at: number
}

export const skillsApi = {
  list: async () => api.get<{ skills: SkillItem[] }>('/skills/list'),
  installLocal: async (path: string) =>
    api.post<{ status: string; installed: SkillItem[]; message: string }>('/skills/install/local', { path }),
  installUrl: async (url: string) =>
    api.post<{ status: string; installed: SkillItem[]; message: string }>('/skills/install/url', { url }),
  remove: async (skillId: string) =>
    api.delete<{ status: string; skill_id: string; message: string }>(`/skills/${encodeURIComponent(skillId)}`)
}
