import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

export const useSessionStore = defineStore('session', () => {
  const currentSessionId = ref<string | null>(localStorage.getItem('crabclaw.session_id'))

  function setSessionId(id: string | null) {
    currentSessionId.value = id
  }

  function syncFromStorage() {
    currentSessionId.value = localStorage.getItem('crabclaw.session_id')
  }

  watch(currentSessionId, (val) => {
    if (val) {
      localStorage.setItem('crabclaw.session_id', val)
    } else {
      localStorage.removeItem('crabclaw.session_id')
    }
  })

  return { currentSessionId, setSessionId, syncFromStorage }
})
