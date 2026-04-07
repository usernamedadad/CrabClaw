import { API_BASE } from './index'

export interface StreamEvent {
  type: 'session' | 'chunk' | 'done' | 'error'
  content?: string
  session_id?: string | null
  error?: string
}

export interface ChatResponse {
  content: string
  session_id: string | null
}

export type StreamCallback = (event: StreamEvent) => void

async function openStream(path: string, body: object, signal?: AbortSignal): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  })
}

export const chatApi = {
  async sendMessageStream(
    message: string,
    sessionId: string | null | undefined,
    skillId: string | null | undefined,
    onEvent: StreamCallback,
    signal?: AbortSignal
  ): Promise<ChatResponse> {
    const body = { message, session_id: sessionId, skill_id: skillId || null }
    const paths = ['/chat', '/chat/send/stream']

    let response: Response | null = null
    for (const path of paths) {
      const res = await openStream(path, body, signal)
      if (res.ok) {
        response = res
        break
      }
    }

    if (!response || !response.ok) {
      throw new Error(`Unable to connect stream endpoint`) 
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No stream body')

    const decoder = new TextDecoder()
    let buffer = ''
    let activeEvent = ''
    let fullText = ''
    let finalSessionId = sessionId ?? null

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue

          if (trimmed.startsWith('event:')) {
            activeEvent = trimmed.slice(6).trim()
            continue
          }

          if (!trimmed.startsWith('data:') || !activeEvent) continue

          const raw = trimmed.slice(5).trim()
          try {
            const parsed = JSON.parse(raw)
            if (activeEvent === 'session') {
              finalSessionId = parsed.session_id ?? null
              onEvent({ type: 'session', session_id: finalSessionId })
            } else if (activeEvent === 'chunk') {
              const content = parsed.content || ''
              fullText += content
              onEvent({ type: 'chunk', content })
            } else if (activeEvent === 'done') {
              finalSessionId = parsed.session_id ?? finalSessionId
              onEvent({ type: 'done', content: parsed.content || fullText, session_id: finalSessionId })
            } else if (activeEvent === 'error') {
              onEvent({ type: 'error', error: parsed.error || 'Unknown error' })
            }
          } catch {
            // ignore malformed SSE lines
          }

          activeEvent = ''
        }
      }
    } finally {
      reader.releaseLock()
    }

    return { content: fullText, session_id: finalSessionId }
  }
}
