<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1 class="logo">ChatSQL</h1>
        <div class="header-actions">
          <button class="icon-btn-header" @click="showSettings = true" title="设置">⚙️</button>
          <button class="icon-btn-header" @click="toggleTheme" :title="theme === 'light' ? '切换深色' : '切换浅色'">
            {{ theme === 'light' ? '🌙' : '☀️' }}
          </button>
        </div>
        <button class="new-chat-btn" @click="createNewSession">+ 新对话</button>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === currentSessionId }"
          @click="selectSession(s.id)"
        >
          <span class="session-title">{{ s.title }}</span>
          <span v-if="s.streaming" class="streaming-dot"></span>
        </div>
        <div v-if="sessions.length === 0" class="empty-hint">
          暂无对话，点击上方开始
        </div>
      </div>
      <div class="sidebar-footer">
        <div class="mode-toggle">
          <button
            :class="{ active: mode === 'fast' }"
            @click="mode = 'fast'"
          >快速</button>
          <button
            :class="{ active: mode === 'think' }"
            @click="mode = 'think'"
          >深度</button>
        </div>
      </div>
    </aside>

    <!-- Main Chat Area -->
    <main class="chat-area">
      <!-- Messages -->
      <div class="messages" ref="messagesRef">
        <div
          v-for="turn in turns"
          :key="turn.response_id"
          class="turn"
        >
          <!-- User message (RIGHT) -->
          <div class="msg-row user-row" v-if="getUserText(turn.request_input)">
            <div class="bubble user-bubble">
              <div class="bubble-avatar">🧑</div>
              <div class="bubble-content">
                {{ getUserText(turn.request_input) }}
              </div>
            </div>
          </div>

          <!-- Assistant section (LEFT) -->
          <div class="msg-row assistant-row">
            <div class="bubble assistant-bubble">
              <div class="bubble-avatar">🤖</div>
              <div class="bubble-content">
                <!-- Tool calls -->
                <template v-for="item in turn.output.filter(o => o.type === 'function_call')" :key="item.id">
                  <!-- Planning -->
                  <div v-if="item.name === 'planning'" class="tool-card planning-card">
                    <div class="tool-header" @click="item._open = !item._open">
                      <span class="tool-icon">📋</span>
                      <span class="tool-name">分析规划</span>
                      <span class="tool-toggle">{{ item._open ? '▼' : '▶' }}</span>
                    </div>
                    <div class="tool-body" v-if="item._open !== false">
                      <template v-if="parseArgs(item.arguments).overview">
                        <p class="overview">{{ parseArgs(item.arguments).overview }}</p>
                      </template>
                      <div
                        v-for="step in parseArgs(item.arguments).steps || []"
                        :key="step.id"
                        class="step"
                      >
                        <span class="step-num">{{ step.id }}</span>
                        <span class="step-title">{{ step.title }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- Chart -->
                  <div v-else-if="item.name === 'smartbot_chart'" class="tool-card chart-card">
                    <div class="tool-header">
                      <span class="tool-icon">📊</span>
                      <span class="tool-name">数据图表</span>
                    </div>
                    <div class="tool-body">
                      <ChartCard :args="parseArgs(item.arguments)" />
                    </div>
                  </div>

                  <!-- Clarification -->
                  <div v-else-if="item.name === 'ask_clarification'" class="tool-card clarification-card">
                    <div class="tool-header">
                      <span class="tool-icon">❓</span>
                      <span class="tool-name">追问</span>
                    </div>
                    <div class="tool-body">
                      <p>{{ parseArgs(item.arguments).question }}</p>
                    </div>
                  </div>

                  <!-- Subscription -->
                  <div v-else-if="item.name === 'propose_subscription'" class="tool-card subscription-card">
                    <div class="tool-header">
                      <span class="tool-icon">🔔</span>
                      <span class="tool-name">订阅建议</span>
                    </div>
                    <div class="tool-body">
                      <p>{{ parseArgs(item.arguments).message || '建议创建定时推送' }}</p>
                    </div>
                  </div>

                  <!-- Generic tool call -->
                  <div v-else class="tool-card generic-card">
                    <div class="tool-header" @click="item._open = !item._open">
                      <span class="tool-icon">🔧</span>
                      <span class="tool-name">{{ item.name || '工具调用' }}</span>
                      <span class="tool-toggle">{{ item._open ? '▼' : '▶' }}</span>
                    </div>
                    <div class="tool-body" v-if="item._open">
                      <pre class="tool-args">{{ JSON.stringify(parseArgs(item.arguments), null, 2) }}</pre>
                    </div>
                  </div>
                </template>

                <!-- Assistant text -->
                <div
                  class="assistant-text"
                  v-for="item in turn.output.filter(o => o.type === 'message')"
                  :key="item.id"
                >
                  {{ getOutputText(item) }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Streaming indicator -->
        <div v-if="isStreaming" class="msg-row assistant-row">
          <div class="bubble assistant-bubble">
            <div class="bubble-avatar">🤖</div>
            <div class="bubble-content">
              <span class="streaming-dots"><span></span><span></span><span></span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- Input area -->
      <div class="input-area">
        <div class="suggested" v-if="suggested.length && turns.length === 0">
          <button
            v-for="q in suggested"
            :key="q"
            class="suggested-btn"
            @click="sendMessage(q)"
          >{{ q }}</button>
        </div>
        <div class="input-row">
          <input
            v-model="userInput"
            placeholder="输入你的问题..."
            @keydown.enter="sendMessage()"
            :disabled="isStreaming"
          />
          <button class="primary" @click="sendMessage()" :disabled="isStreaming || !userInput.trim()">
            发送
          </button>
        </div>
      </div>
    </main>

    <!-- Settings Panel -->
    <SettingsView v-if="showSettings" @close="showSettings = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import ChartCard from './components/ChartCard.vue'
import SettingsView from './components/SettingsView.vue'

interface Session {
  id: string
  title: string
  mode: string
  streaming: boolean
}

interface Turn {
  response_id: string
  request_input: any[]
  output: any[]
  created_at: number
  feedback: string | null
}

// State
const sessions = ref<Session[]>([])
const currentSessionId = ref<string>('')
const turns = ref<Turn[]>([])
const userInput = ref('')
const isStreaming = ref(false)
const mode = ref<'fast' | 'think'>('fast')
const suggested = ref<string[]>([])
const messagesRef = ref<HTMLElement>()
const showSettings = ref(false)
const theme = ref<'light' | 'dark'>('light')

// Theme toggle
function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  document.documentElement.setAttribute('data-theme', theme.value)
  localStorage.setItem('chatsql_theme', theme.value)
}

// Load saved theme
const savedTheme = localStorage.getItem('chatsql_theme')
if (savedTheme === 'dark' || savedTheme === 'light') {
  theme.value = savedTheme
  document.documentElement.setAttribute('data-theme', theme.value)
}

// API base
const API = '/v1'

// ── Lifecycle ──
onMounted(async () => {
  await loadSessions()
  await loadSuggested()
})

// ── Sessions ──
async function loadSessions() {
  try {
    const res = await fetch(`${API}/sessions`)
    sessions.value = await res.json()
  } catch (e) {
    console.error('Failed to load sessions', e)
  }
}

async function loadSuggested() {
  try {
    const res = await fetch(`${API}/suggested`)
    const data = await res.json()
    suggested.value = data.data || []
  } catch (e) {
    console.error('Failed to load suggested', e)
  }
}

async function createNewSession() {
  // Session is created on first message — just clear state
  currentSessionId.value = ''
  turns.value = []
  userInput.value = ''
}

async function selectSession(sessionId: string) {
  currentSessionId.value = sessionId
  // Load turns
  try {
    const res = await fetch(`${API}/sessions/${sessionId}/response-turns`)
    const data = await res.json()
    turns.value = data.turns || []
    // Set mode from session
    const s = sessions.value.find(s => s.id === sessionId)
    if (s?.mode) mode.value = s.mode as 'fast' | 'think'
    await scrollToBottom()
  } catch (e) {
    console.error('Failed to load turns', e)
  }
}

// ── Send message ──
async function sendMessage(text?: string) {
  const content = (text || userInput.value).trim()
  if (!content || isStreaming.value) return

  userInput.value = ''
  isStreaming.value = true

  // Optimistic: add user message to UI
  const tempTurn: Turn = {
    response_id: `temp_${Date.now()}`,
    request_input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: content }] }],
    output: [],
    created_at: Math.floor(Date.now() / 1000),
    feedback: null,
  }
  turns.value.push(tempTurn)
  await scrollToBottom()

  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-SmartBot-Mode': mode.value,
    }
    if (currentSessionId.value) {
      headers['X-Session-Id'] = currentSessionId.value
    }

    const res = await fetch(`${API}/responses`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        input: content,
        stream: true,
      }),
    })

    // Extract session ID from headers
    const sessionId = res.headers.get('X-Session-Id')
    if (sessionId && !currentSessionId.value) {
      currentSessionId.value = sessionId
    }

    // Read SSE stream
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let outputItems: any[] = []
    let currentText = ''
    let responseId = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = line.slice(6).trim()
        if (data === '[DONE]') continue

        try {
          const event = JSON.parse(data)

          if (event.type === 'response.created') {
            responseId = event.response.id
            tempTurn.response_id = responseId
          } else if (event.type === 'response.output_text.delta') {
            currentText += event.delta
            // Update or create message item
            let msgItem = outputItems.find(o => o.type === 'message')
            if (!msgItem) {
              msgItem = {
                type: 'message',
                id: `msg_${responseId}`,
                role: 'assistant',
                content: [{ type: 'output_text', text: currentText }],
                status: 'completed',
              }
              outputItems.push(msgItem)
            } else {
              msgItem.content[0].text = currentText
            }
            tempTurn.output = [...outputItems]
          } else if (event.type === 'response.function_call_arguments.done') {
            // Find or create function call item
            let fcItem = outputItems.find(o => o.type === 'function_call' && o.call_id === event.call_id)
            if (!fcItem) {
              fcItem = {
                type: 'function_call',
                id: `fc_${responseId}_${outputItems.length}`,
                call_id: event.call_id,
                name: '', // Will be set from earlier event
                arguments: event.arguments,
                status: 'completed',
              }
              outputItems.push(fcItem)
            } else {
              fcItem.arguments = event.arguments
            }
            tempTurn.output = [...outputItems]
          } else if (event.type === 'response.output_item.added') {
            if (event.item.type === 'function_call') {
              outputItems.push(event.item)
              tempTurn.output = [...outputItems]
            }
          } else if (event.type === 'response.completed') {
            outputItems = event.response.output || outputItems
            tempTurn.output = [...outputItems]
          }
        } catch (e) {
          // Ignore parse errors for partial JSON
        }
      }
      await scrollToBottom()
    }

    // Reload sessions to get updated titles
    await loadSessions()
  } catch (e) {
    console.error('Failed to send message', e)
    // Show error in UI
    tempTurn.output.push({
      type: 'message',
      id: `err_${Date.now()}`,
      role: 'assistant',
      content: [{ type: 'output_text', text: '⚠️ 请求失败，请检查网络或后端服务' }],
      status: 'completed',
    })
  } finally {
    isStreaming.value = false
    await scrollToBottom()
  }
}

// ── Helpers ──
function getUserText(input: any[]): string {
  for (const item of input) {
    if (item.type === 'message' && item.role === 'user') {
      return item.content?.map((c: any) => c.text || '').join(' ') || ''
    }
  }
  return ''
}

function getOutputText(item: any): string {
  return item.content?.map((c: any) => c.text || '').join(' ') || ''
}

function parseArgs(args: string): any {
  try {
    return JSON.parse(args)
  } catch {
    return {}
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100%;
}

/* Sidebar */
.sidebar {
  width: 260px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}
.logo {
  font-size: 18px;
  font-weight: 700;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.header-actions {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}
.icon-btn-header {
  background: none;
  border: 1px solid var(--border);
  padding: 4px 8px;
  cursor: pointer;
  border-radius: var(--radius);
  font-size: 14px;
}
.icon-btn-header:hover {
  background: var(--bg-tertiary);
}
.new-chat-btn {
  width: 100%;
  text-align: left;
  padding: 10px 14px;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-item {
  padding: 10px 12px;
  border-radius: var(--radius);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  transition: background 0.2s;
}
.session-item:hover {
  background: var(--bg-tertiary);
}
.session-item.active {
  background: var(--accent-light);
  border: 1px solid var(--accent);
}
.session-title {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.streaming-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  animation: pulse 1.5s infinite;
}
.empty-hint {
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
  padding: 20px;
}
.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border);
}
.mode-toggle {
  display: flex;
  gap: 4px;
}
.mode-toggle button {
  flex: 1;
  padding: 6px;
  font-size: 12px;
}
.mode-toggle button.active {
  background: var(--accent);
  color: white;
}

/* Chat Area */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

/* Turn */
.turn { margin-bottom: 24px; }

/* Message rows */
.msg-row { display: flex; margin-bottom: 8px; }
.user-row { justify-content: flex-end; }
.assistant-row { justify-content: flex-start; }

/* Bubbles */
.bubble { display: flex; gap: 10px; max-width: 85%; }
.user-row .bubble { flex-direction: row-reverse; }
.bubble-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
  background: var(--bg-tertiary);
}
.bubble-content { flex: 1; min-width: 0; }

/* User bubble */
.user-bubble .bubble-content {
  background: var(--accent);
  color: white;
  padding: 12px 16px;
  border-radius: 16px 16px 4px 16px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

/* Assistant bubble */
.assistant-bubble .bubble-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  padding: 16px;
  border-radius: 16px 16px 16px 4px;
  font-size: 14px;
  line-height: 1.7;
}
.assistant-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* Tool cards */
.tool-card {
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-tertiary);
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  font-weight: 600;
}
.tool-icon { font-size: 15px; }
.tool-name { flex: 1; color: var(--text-secondary); }
.tool-toggle { font-size: 11px; color: var(--text-muted); }
.tool-body { padding: 12px 14px; }
.tool-args {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  overflow-x: auto;
  color: var(--text-primary);
  margin: 0;
  max-height: 300px;
  overflow-y: auto;
}

/* Planning card */
.planning-card .tool-header { background: rgba(59, 130, 246, 0.08); }
.planning-card .tool-name { color: #3b82f6; }
.overview { color: var(--text-secondary); margin-bottom: 12px; font-size: 13px; }
.step { display: flex; gap: 10px; padding: 6px 0; }
.step-num {
  width: 24px; height: 24px;
  border-radius: 50%;
  background: var(--accent);
  color: white;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
}
.step-title { font-size: 13px; }

/* Chart card */
.chart-card .tool-header { background: rgba(16, 185, 129, 0.08); }
.chart-card .tool-name { color: #10b981; }

/* Clarification card */
.clarification-card { border-color: var(--warning); }
.clarification-card .tool-header { background: rgba(245, 158, 11, 0.08); }
.clarification-card .tool-name { color: #f59e0b; }

/* Subscription card */
.subscription-card .tool-header { background: rgba(139, 92, 246, 0.08); }
.subscription-card .tool-name { color: #8b5cf6; }

/* Generic tool card */
.generic-card .tool-header { background: var(--bg-tertiary); }

/* Streaming dots */
.streaming-dots { display: flex; gap: 4px; padding: 4px 0; }
.streaming-dots span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: blink 1.4s infinite both;
}
.streaming-dots span:nth-child(2) { animation-delay: 0.2s; }
.streaming-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink {
  0%, 80%, 100% { opacity: 0.3; }
  40% { opacity: 1; }
}

/* Streaming */

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

/* Input */
.input-area {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}
.suggested {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.suggested-btn {
  font-size: 12px;
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
}
.suggested-btn:hover {
  border-color: var(--accent);
}
.input-row {
  display: flex;
  gap: 8px;
}
.input-row input {
  flex: 1;
}
</style>
