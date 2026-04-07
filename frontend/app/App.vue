<template>
  <div class="shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }" :data-theme="isDark ? 'dark' : 'light'">
    <SidebarNav :collapsed="sidebarCollapsed" :dark-mode="isDark" @toggle="toggleSidebar" @toggle-theme="toggleTheme" />
    <main class="main">
      <router-view v-slot="{ Component }">
        <KeepAlive>
          <component :is="Component" />
        </KeepAlive>
      </router-view>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import SidebarNav from './components/SidebarNav.vue'

const SIDEBAR_COLLAPSE_KEY = 'crabclaw.sidebar_collapsed'
const THEME_KEY = 'crabclaw.theme'
const sidebarCollapsed = ref(localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === '1')
const isDark = ref(localStorage.getItem(THEME_KEY) === 'dark')

function applyThemeToBody() {
  document.body.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem(SIDEBAR_COLLAPSE_KEY, sidebarCollapsed.value ? '1' : '0')
}

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem(THEME_KEY, isDark.value ? 'dark' : 'light')
}

onMounted(() => {
  applyThemeToBody()
})

watch(isDark, () => {
  applyThemeToBody()
})
</script>
