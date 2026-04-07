import { createRouter, createWebHistory } from 'vue-router'

import ChatView from './pages/ChatView.vue'
import SessionsView from './pages/SessionsView.vue'
import MemoryView from './pages/MemoryView.vue'
import ConfigView from './pages/ConfigView.vue'
import SkillsView from './pages/SkillsView.vue'
import ToolLogView from './pages/ToolLogView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/sessions', component: SessionsView },
    { path: '/skills', component: SkillsView },
    { path: '/memory', component: MemoryView },
    { path: '/tool-log', component: ToolLogView },
    { path: '/config', component: ConfigView }
  ]
})

export default router
