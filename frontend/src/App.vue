<template>
  <div class="app-layout">
    <!-- Navigation Sidebar -->
    <Sidebar
      :currentView="currentView"
      :isDark="theme === 'dark'"
      @navigate="currentView = $event"
      @toggle-theme="toggleTheme"
    />

    <!-- Chat View -->
    <template v-if="currentView === 'chat'">
      <!-- Session Sidebar -->
      <aside class="session-sidebar">
        <div class="sidebar-header">
          <button class="new-chat-btn" @click="createNewSession">+ 新对话</button>
          <div class="mode-toggle">
            <button
              :class="{ active: mode === 'fast' }"
              @click="mode = 'fast'"
            >⚡ 快速</button>
            <button
              :class="{ active: mode === 'think' }"
              @click="mode = 'think'"
            >🧠 深度</button>
          </div>
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
                        <button class="save-chart-btn" @click="saveChartToDashboard(item)" title="保存到仪表盘">💾</button>
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

                    <!-- Execute SQL -->
                    <div v-else-if="item.name === 'execute_sql'" class="tool-card sql-card">
                      <div class="tool-header" @click="item._open = !item._open">
                        <span class="tool-icon">🗃️</span>
                        <span class="tool-name">SQL 查询</span>
                        <span class="tool-toggle">{{ item._open ? '▼' : '▶' }}</span>
                      </div>
                      <div class="tool-body" v-if="item._open !== false">
                        <pre class="sql-code">{{ parseArgs(item.arguments).sql }}</pre>
                        <div v-if="item._result" class="sql-result">
                          <div class="result-meta">
                            <span>✅ {{ item._result.row_count ?? item._result.rows?.length ?? 0 }} 条结果</span>
                          </div>
                          <div class="result-table-wrap" v-if="item._result.columns?.length">
                            <table class="result-table">
                              <thead>
                                <tr>
                                  <th v-for="col in item._result.columns" :key="col.name">{{ col.name }}</th>
                                </tr>
                              </thead>
                              <tbody>
                                <tr v-for="(row, ri) in (item._result.rows || []).slice(0, 100)" :key="ri">
                                  <td v-for="col in item._result.columns" :key="col.name">{{ row[col.name] ?? '' }}</td>
                                </tr>
                              </tbody>
                            </table>
                            <div v-if="(item._result.rows?.length || 0) > 100" class="result-more">
                              显示前 100 条，共 {{ item._result.rows.length }} 条
                            </div>
                          </div>
                          <div v-if="item._result.error" class="result-error">
                            ❌ {{ item._result.error }}
                          </div>
                        </div>
                        <div v-else class="sql-loading">执行中...</div>
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
    </template>

    <!-- Dashboard View -->
    <DashboardView v-else-if="currentView === 'dashboard'" />

    <!-- Settings View -->
    <div v-else-if="currentView === 'settings'" class="settings-view">
      <SettingsView @close="currentView = 'chat'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import ChartCard from './components/ChartCard.vue'
import SettingsView from './components/SettingsView.vue'
import Sidebar from './components/Sidebar.vue'
import DashboardView from './components/DashboardView.vue'

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
const theme = ref<'light' | 'dark'>('light')
const currentView = ref<'chat' | 'dashboard' | 'settings'>('chat')

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
  currentSessionId.value = ''
  turns.value = []
  userInput.value = ''
}

async function selectSession(sessionId: string) {
  currentSessionId.value = sessionId
  try {
    const res = await fetch(`${API}/sessions/${sessionId}/response-turns`)
    const data = await res.json()
    turns.value = data.turns || []
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
      body: JSON.stringify({ input: content, stream: true }),
    })

    const sessionId = res.headers.get('X-Session-Id')
    if (sessionId && !currentSessionId.value) {
      currentSessionId.value = sessionId
    }

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
            let fcItem = outputItems.find(o => o.type === 'function_call' && o.call_id === event.call_id)
            if (!fcItem) {
              fcItem = {
                type: 'function_call',
                id: `fc_${responseId}_${outputItems.length}`,
                call_id: event.call_id,
                name: '',
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
          } else if (event.type === 'tool_result') {
            let fcItem = outputItems.find(o => o.type === 'function_call' && o.call_id === event.call_id)
            if (fcItem) {
              fcItem._result = event.result
              tempTurn.output = [...outputItems]
            }
          } else if (event.type === 'response.completed') {
            outputItems = event.response.output || outputItems
            tempTurn.output = [...outputItems]
          }
        } catch (e) {
          // Ignore parse errors
        }
      }
      await scrollToBottom()
    }

    await loadSessions()
  } catch (e) {
    console.error('Failed to send message', e)
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

// ── Save chart to dashboard ──
async function saveChartToDashboard(item: any) {
  const args = parseArgs(item.arguments)
  try {
    // First get or create a default dashboard
    const listRes = await fetch(`${API}/dashboards`)
    let dashboards = await listRes.json()
    let dashboardId = dashboards[0]?.id

    if (!dashboardId) {
      const createRes = await fetch(`${API}/dashboards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: '默认仪表盘' }),
      })
      const d = await createRes.json()
      dashboardId = d.id
    }

    await fetch(`${API}/dashboards/save-chart`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dashboard_id: dashboardId,
        chart_data: {
          title: args.chart?.title || '图表',
          chart_type: args.chart?.type || 'table',
          config: args,
          data: args.data || {},
          sql: args.sql || '',
        },
      }),
    })
    alert('✅ 已保存到仪表盘')
  } catch (e) {
    console.error('Failed to save chart', e)
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
  try { return JSON.parse(args) } catch { return {} }
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
  overflow: hidden;
}

/* Session Sidebar */
.session-sidebar {
  width: 240px;
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

.new-chat-btn {
  width: 100%;
  text-align: left;
  padding: 10px 14px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 14px;
  margin-bottom: 10px;
  transition: background 0.2s;
}

.new-chat-btn:hover {
  background: var(--accent-hover);
}

.mode-toggle {
  display: flex;
  gap: 4px;
  background: var(--bg-tertiary);
  border-radius: var(--radius);
  padding: 3px;
}

.mode-toggle button {
  flex: 1;
  padding: 6px 10px;
  border: none;
  background: transparent;
  border-radius: 5px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.mode-toggle button.active {
  background: var(--bg-primary);
  color: var(--text);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
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
  transition: background 0.2s;
  font-size: 13px;
}

.session-item:hover {
  background: var(--bg-hover);
}

.session-item.active {
  background: var(--accent-bg);
  color: var(--accent);
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.streaming-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse 1.5s infinite;
  flex-shrink: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.empty-hint {
  text-align: center;
  color: var(--text-muted);
  padding: 32px 16px;
  font-size: 13px;
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
  scroll-behavior: smooth;
}

.turn {
  margin-bottom: 20px;
}

.msg-row {
  display: flex;
  margin-bottom: 8px;
}

.user-row {
  justify-content: flex-end;
}

.assistant-row {
  justify-content: flex-start;
}

.bubble {
  display: flex;
  gap: 10px;
  max-width: 85%;
}

.bubble-avatar {
  font-size: 20px;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bubble-content {
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.user-bubble {
  flex-direction: row-reverse;
}

.user-bubble .bubble-content {
  background: var(--accent);
  color: white;
  border-bottom-right-radius: 4px;
}

.assistant-bubble .bubble-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  width: 100%;
  min-width: 0;
}

/* Tool cards */
.tool-card {
  margin: 8px 0;
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--border);
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}

.tool-icon { font-size: 16px; }
.tool-name { font-size: 13px; font-weight: 600; flex: 1; }
.tool-toggle { font-size: 11px; color: var(--text-muted); }

.tool-body {
  padding: 8px 12px 12px;
  font-size: 13px;
  border-top: 1px solid var(--border);
}

.planning-card { background: #eff6ff; border-color: #bfdbfe; }
.chart-card { background: #f0fdf4; border-color: #bbf7d0; }
.clarification-card { background: #fefce8; border-color: #fde68a; }
.subscription-card { background: #faf5ff; border-color: #e9d5ff; }
.sql-card { background: #f8fafc; border-color: #cbd5e1; }
.generic-card { background: var(--bg-tertiary); }

.overview {
  margin: 0 0 8px;
  font-weight: 500;
  color: #1e40af;
}

.step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}

.step-num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  color: white;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.step-title {
  font-size: 13px;
}

.sql-code {
  background: #1e293b;
  color: #e2e8f0;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  overflow-x: auto;
  margin: 0 0 8px;
}

.sql-result { margin-top: 8px; }

.result-meta {
  font-size: 12px;
  color: #16a34a;
  margin-bottom: 8px;
}

.result-table-wrap {
  max-height: 300px;
  overflow: auto;
  border-radius: 8px;
  border: 1px solid var(--border);
}

.result-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.result-table th {
  position: sticky;
  top: 0;
  background: var(--bg-tertiary);
  padding: 6px 10px;
  text-align: left;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.result-table td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-table tr:hover td {
  background: var(--bg-hover);
}

.result-more {
  text-align: center;
  padding: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.result-error {
  color: #dc2626;
  font-size: 13px;
  padding: 8px;
  background: #fef2f2;
  border-radius: 6px;
}

.sql-loading {
  color: var(--text-muted);
  font-size: 13px;
  padding: 8px 0;
}

.tool-args {
  background: #1e293b;
  color: #e2e8f0;
  padding: 10px;
  border-radius: 6px;
  font-size: 11px;
  overflow-x: auto;
  margin: 0;
}

.assistant-text {
  padding: 4px 0;
  white-space: pre-wrap;
}

.save-chart-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.2s;
}

.save-chart-btn:hover {
  background: rgba(0,0,0,0.08);
}

/* Streaming dots */
.streaming-dots {
  display: inline-flex;
  gap: 4px;
  padding: 4px 0;
}

.streaming-dots span {
  width: 8px;
  height: 8px;
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

/* Input area */
.input-area {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg-primary);
}

.suggested {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.suggested-btn {
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--bg-secondary);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.suggested-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.input-row {
  display: flex;
  gap: 10px;
}

.input-row input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 14px;
  background: var(--bg-primary);
  transition: border-color 0.2s;
}

.input-row input:focus {
  outline: none;
  border-color: var(--accent);
}

.input-row button.primary {
  padding: 12px 28px;
}

/* Settings view */
.settings-view {
  flex: 1;
  overflow-y: auto;
}
</style>
