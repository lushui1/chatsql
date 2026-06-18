<template>
  <div class="settings-overlay" @click.self="$emit('close')">
    <!-- Toast notification -->
    <Transition name="toast">
      <div v-if="toast.visible" :class="['toast', toast.type]">
        {{ toast.message }}
      </div>
    </Transition>

    <div class="settings-panel">
      <div class="settings-header">
        <h2>⚙️ 设置</h2>
        <button class="close-btn" @click="$emit('close')">✕</button>
      </div>

      <div class="settings-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >{{ tab.icon }} {{ tab.label }}</button>
      </div>

      <div class="settings-body">
        <!-- Data Sources Tab -->
        <div v-if="activeTab === 'datasources'" class="tab-content">
          <div class="section-header">
            <h3>数据源管理</h3>
            <button class="small-btn" @click="showAddSource = true">+ 添加数据源</button>
          </div>

          <div class="source-list">
            <div v-for="s in sources" :key="s.name" class="source-card">
              <div class="source-info">
                <span class="source-type">{{ typeIcons[s.type] || '🗄️' }}</span>
                <div>
                  <div class="source-name">{{ s.name }}</div>
                  <div class="source-desc">{{ s.type }} · {{ s.host || 'local' }}{{ s.database ? '/' + s.database : '' }}</div>
                </div>
              </div>
              <div class="source-actions">
                <button class="icon-btn" @click="viewMetadata(s.name)" title="查看表结构">📋</button>
                <button class="icon-btn" @click="removeSource(s.name)" title="删除">🗑️</button>
              </div>
            </div>
            <div v-if="sources.length === 0" class="empty-state">
              暂无数据源，点击上方添加
            </div>
          </div>

          <!-- Add Source Form -->
          <div v-if="showAddSource" class="add-form">
            <h4>添加数据源</h4>
            <div class="form-grid">
              <label>名称<input v-model="newSource.name" placeholder="my-mysql" /></label>
              <label>类型
                <select v-model="newSource.type">
                  <option v-for="t in sourceTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
                </select>
              </label>
              <label>主机<input v-model="newSource.host" placeholder="localhost" /></label>
              <label>端口<input v-model.number="newSource.port" :placeholder="defaultPort" type="number" /></label>
              <label>数据库<input v-model="newSource.database" placeholder="analytics" /></label>
              <label>用户名<input v-model="newSource.username" placeholder="root" /></label>
              <label>密码<input v-model="newSource.password" type="password" placeholder="••••" /></label>
            </div>
            <div v-if="testSourceResult" :class="['test-banner', testSourceResult.ok ? 'test-success' : 'test-error']">
              <span class="test-icon">{{ testSourceResult.ok ? '✅' : '❌' }}</span>
              <span>{{ testSourceResult.msg }}</span>
            </div>
            <div class="form-actions">
              <button class="small-btn" @click="testSource" :disabled="testingSource">
                {{ testingSource ? '测试中...' : '🔗 测试连接' }}
              </button>
              <button class="small-btn" @click="addSource" :disabled="!testSourceResult?.ok">
                💾 保存
              </button>
              <button class="small-btn secondary" @click="showAddSource = false; testSourceResult = null">取消</button>
            </div>
          </div>

          <!-- Metadata Viewer -->
          <div v-if="metadataView" class="metadata-view">
            <h4>📋 {{ metadataView.source }} 表结构</h4>
            <div v-for="t in metadataView.tables" :key="t.name" class="table-card">
              <div class="table-name" @click="t._open = !t._open">
                {{ t._open ? '📂' : '📁' }} {{ t.name }}
                <span class="col-count">{{ t.columns.length }} 列</span>
              </div>
              <div v-if="t._open" class="table-columns">
                <div class="col-header"><span>列名</span><span>类型</span><span>可空</span><span>说明</span></div>
                <div v-for="c in t.columns" :key="c.name" class="col-row">
                  <span class="col-name">{{ c.name }}</span>
                  <span class="col-type">{{ c.type }}</span>
                  <span class="col-nullable">{{ c.nullable ? '✓' : '✗' }}</span>
                  <span class="col-comment">{{ c.comment || '-' }}</span>
                </div>
              </div>
            </div>
            <button class="small-btn secondary" @click="metadataView = null">关闭</button>
          </div>
        </div>

        <!-- LLM Config Tab -->
        <div v-if="activeTab === 'llm'" class="tab-content">
          <h3>大模型配置</h3>
          <div class="llm-config">
            <label>Provider
              <select v-model="llmConfig.provider">
                <option v-for="p in providers" :key="p" :value="p">{{ p }}</option>
              </select>
            </label>
            <label>API Key
              <input v-model="llmConfig.apiKey" type="password" placeholder="sk-..." />
            </label>
            <label>Base URL
              <input v-model="llmConfig.baseUrl" :placeholder="providerDefaults.base_url" />
            </label>
            <label>快速模型 (fast)
              <input v-model="llmConfig.model" :placeholder="providerDefaults.models?.[0]" />
            </label>
            <label>深度模型 (think)
              <input v-model="llmConfig.thinkModel" :placeholder="providerDefaults.models?.[1] || providerDefaults.models?.[0]" />
            </label>
            <label>温度 (Temperature)
              <input v-model.number="llmConfig.temperature" type="number" step="0.1" min="0" max="2" placeholder="0.3" />
            </label>
            <label>最大 Tokens
              <input v-model.number="llmConfig.maxTokens" type="number" step="256" min="256" max="128000" placeholder="4096" />
            </label>
          </div>
          <div class="form-actions">
            <button class="small-btn" @click="saveLLMConfig" :disabled="llmSaving">
              {{ llmSaving ? '保存中...' : '💾 保存配置' }}
            </button>
            <span v-if="llmSaved" class="saved-hint">✅ 已保存并生效</span>
          </div>

          <div class="provider-list">
            <h4>支持的 Provider</h4>
            <div v-for="p in providers" :key="p" class="provider-item" @click="llmConfig.provider = p">
              <span class="provider-name">{{ p }}</span>
              <span class="provider-models">{{ providerMap[p]?.models?.slice(0, 3).join(', ') }}</span>
            </div>
          </div>
        </div>

        <!-- System Info Tab -->
        <div v-if="activeTab === 'system'" class="tab-content">
          <h3>系统信息</h3>
          <div class="info-grid">
            <div class="info-item"><span class="info-label">版本</span><span>v0.1.0</span></div>
            <div class="info-item"><span class="info-label">后端</span><span>http://127.0.0.1:8000</span></div>
            <div class="info-item"><span class="info-label">数据源</span><span>{{ sources.length }} 个</span></div>
            <div class="info-item"><span class="info-label">Provider</span><span>{{ llmConfig.provider }}</span></div>
            <div class="info-item"><span class="info-label">模型</span><span>{{ llmConfig.model || '未配置' }}</span></div>
          </div>
          <div class="form-actions" style="margin-top:20px">
            <button class="small-btn" @click="testConnection">测试后端连接</button>
            <span v-if="testResult" :class="testResult.ok ? 'saved-hint' : 'error-hint'">{{ testResult.msg }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

defineEmits(['close'])

const activeTab = ref('datasources')
const tabs = [
  { key: 'datasources', icon: '🗄️', label: '数据源' },
  { key: 'llm', icon: '🤖', label: '大模型' },
  { key: 'system', icon: 'ℹ️', label: '系统' },
]

// ── Toast ──
const toast = ref({ visible: false, message: '', type: 'success' })
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(message: string, type: 'success' | 'error' = 'success') {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { visible: true, message, type }
  toastTimer = setTimeout(() => { toast.value.visible = false }, 3000)
}

// ── Data Sources ──
const sources = ref<any[]>([])
const showAddSource = ref(false)
const metadataView = ref<any>(null)
const newSource = ref({
  name: '', type: 'mysql', host: '', port: 3306, database: '', username: '', password: '',
})
const testSourceResult = ref<{ ok: boolean; msg: string } | null>(null)
const testingSource = ref(false)

const sourceTypes = [
  { value: 'duckdb', label: 'DuckDB' },
  { value: 'mysql', label: 'MySQL' },
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'clickhouse', label: 'ClickHouse' },
  { value: 'hive', label: 'Hive' },
  { value: 'presto', label: 'Presto' },
  { value: 'spark', label: 'Spark SQL' },
  { value: 'doris', label: 'Apache Doris' },
]

const typeIcons: Record<string, string> = {
  duckdb: '🦆', mysql: '🐬', postgresql: '🐘', clickhouse: '⚡',
  hive: '🐝', presto: '🔷', spark: '🔥', doris: '🏔️',
}

const defaultPort = computed(() => {
  const ports: Record<string, number> = {
    duckdb: 0, mysql: 3306, postgresql: 5432, clickhouse: 8123,
    hive: 10000, presto: 8080, spark: 10000, doris: 9030,
  }
  return ports[newSource.value.type] || 3306
})

async function loadSources() {
  try {
    const res = await fetch('/v1/datasources')
    const data = await res.json()
    sources.value = data.sources || []
  } catch (e) { console.error(e) }
}

async function testSource() {
  testingSource.value = true
  testSourceResult.value = null
  try {
    const res = await fetch('/v1/datasources/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSource.value),
    })
    const data = await res.json()
    testSourceResult.value = data
    showToast(data.message, data.ok ? 'success' : 'error')
  } catch (e: any) {
    const msg = `请求失败: ${e.message}`
    testSourceResult.value = { ok: false, msg }
    showToast(msg, 'error')
  } finally {
    testingSource.value = false
  }
}

async function addSource() {
  try {
    const res = await fetch('/v1/datasources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSource.value),
    })
    if (res.ok) {
      showAddSource.value = false
      testSourceResult.value = null
      newSource.value = { name: '', type: 'mysql', host: '', port: 3306, database: '', username: '', password: '' }
      await loadSources()
    } else {
      const data = await res.json()
      testSourceResult.value = { ok: false, msg: data.detail || '保存失败' }
    }
  } catch (e: any) {
    testSourceResult.value = { ok: false, msg: `保存失败: ${e.message}` }
  }
}

async function removeSource(name: string) {
  if (!confirm(`确定删除数据源 "${name}"？`)) return
  try {
    await fetch(`/v1/datasources/${name}`, { method: 'DELETE' })
    await loadSources()
  } catch (e) { console.error(e) }
}

async function viewMetadata(name: string) {
  try {
    const res = await fetch(`/v1/datasources/${name}/full-metadata`)
    const data = await res.json()
    data.tables.forEach((t: any) => t._open = false)
    metadataView.value = data
  } catch (e) { console.error(e) }
}

// ── LLM Config ──
const providers = ['openai', 'anthropic', 'google', 'dashscope', 'zhipu', 'moonshot', 'deepseek', 'ollama', 'custom']
const providerMap: Record<string, any> = {}
const llmConfig = ref({ provider: 'openai', apiKey: '', baseUrl: '', model: '', thinkModel: '', temperature: 0.3, maxTokens: 4096 })
const llmSaved = ref(false)
const llmSaving = ref(false)

const providerDefaults = computed(() => providerMap[llmConfig.value.provider] || {})

async function loadLLMConfig() {
  try {
    const res = await fetch('/v1/config/llm')
    const data = await res.json()
    llmConfig.value.provider = data.provider || 'openai'
    llmConfig.value.baseUrl = data.base_url || ''
    llmConfig.value.model = data.model || ''
    llmConfig.value.thinkModel = data.think_model || ''
    llmConfig.value.temperature = data.temperature ?? 0.3
    llmConfig.value.maxTokens = data.max_tokens ?? 4096
    // Build provider map from available_providers + provider_models
    if (data.available_providers) {
      for (const p of data.available_providers) {
        if (!providerMap[p]) providerMap[p] = { models: [] }
      }
    }
    if (data.provider_models) {
      providerMap[data.provider] = { models: data.provider_models }
    }
  } catch (e) { console.error(e) }
}

async function saveLLMConfig() {
  llmSaving.value = true
  try {
    const res = await fetch('/v1/config/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: llmConfig.value.provider,
        api_key: llmConfig.value.apiKey || undefined,
        base_url: llmConfig.value.baseUrl || undefined,
        model: llmConfig.value.model || undefined,
        think_model: llmConfig.value.thinkModel || undefined,
        temperature: llmConfig.value.temperature,
        max_tokens: llmConfig.value.maxTokens,
      }),
    })
    if (res.ok) {
      llmSaved.value = true
      showToast('LLM 配置已保存并生效', 'success')
      setTimeout(() => llmSaved.value = false, 2000)
      await loadLLMConfig()
    } else {
      showToast('保存失败', 'error')
    }
  } catch (e: any) {
    showToast(`保存失败: ${e.message}`, 'error')
  } finally { llmSaving.value = false }
}

// ── System ──
const testResult = ref<{ ok: boolean; msg: string } | null>(null)

async function testConnection() {
  testResult.value = null
  try {
    const res = await fetch('/healthz')
    if (res.ok) {
      const data = await res.json()
      testResult.value = { ok: true, msg: `✅ 后端连接正常 (${data.service} v${data.version || '?'})` }
      showToast('后端连接正常', 'success')
    } else {
      testResult.value = { ok: false, msg: `❌ 状态码 ${res.status}` }
      showToast(`后端返回 ${res.status}`, 'error')
    }
  } catch (e: any) {
    testResult.value = { ok: false, msg: `❌ 连接失败: ${e.message}` }
    showToast(`连接失败: ${e.message}`, 'error')
  }
}

onMounted(() => {
  loadSources()
  loadLLMConfig()
})
</script>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}
.settings-panel {
  width: 520px;
  max-width: 90vw;
  background: var(--bg-primary);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100%;
  box-shadow: -4px 0 24px rgba(0,0,0,0.1);
}
.settings-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.settings-header h2 { margin: 0; font-size: 16px; }
.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 4px 8px;
}
.settings-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  padding: 0 12px;
}
.settings-tabs button {
  flex: 1;
  padding: 10px 8px;
  font-size: 13px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: var(--text-secondary);
  border-radius: 0;
}
.settings-tabs button.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  background: none;
}
.settings-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.tab-content h3 { margin: 0 0 16px; font-size: 15px; }

/* Source cards */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.section-header h3 { margin: 0; }
.source-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 8px;
}
.source-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.source-type { font-size: 24px; }
.source-name { font-weight: 600; font-size: 14px; }
.source-desc { font-size: 12px; color: var(--text-muted); }
.source-actions { display: flex; gap: 4px; }
.icon-btn {
  background: none;
  border: 1px solid var(--border);
  padding: 4px 8px;
  cursor: pointer;
  border-radius: var(--radius);
  font-size: 14px;
}
.icon-btn:hover { background: var(--bg-tertiary); }
.empty-state {
  text-align: center;
  padding: 32px;
  color: var(--text-muted);
}

/* Add form */
.add-form {
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  padding: 16px;
  margin-top: 16px;
  background: var(--bg-secondary);
}
.add-form h4 { margin: 0 0 12px; }
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}
.form-grid input, .form-grid select {
  padding: 8px;
  font-size: 13px;
}
.form-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  align-items: center;
}
.small-btn {
  padding: 6px 16px;
  font-size: 13px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
}
.small-btn.secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border);
}
.saved-hint { font-size: 13px; color: var(--success); }
.error-hint { font-size: 13px; color: var(--error); }
.test-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  border-radius: var(--radius);
  padding: 14px 16px;
  margin: 16px 0;
  font-size: 14px;
  font-weight: 500;
  animation: fadeIn 0.3s ease;
}
.test-icon { font-size: 18px; flex-shrink: 0; }
.test-success {
  background: rgba(16, 185, 129, 0.12);
  border: 2px solid var(--success);
  color: var(--success);
}
.test-error {
  background: rgba(239, 68, 68, 0.12);
  border: 2px solid var(--error);
  color: var(--error);
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Toast */
.toast {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 200;
  padding: 14px 24px;
  border-radius: var(--radius);
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15);
  max-width: 400px;
}
.toast.success {
  background: #ecfdf5;
  color: #065f46;
  border: 2px solid #10b981;
}
.toast.error {
  background: #fef2f2;
  color: #991b1b;
  border: 2px solid #ef4444;
}
[data-theme="dark"] .toast.success {
  background: #064e3b;
  color: #6ee7b7;
}
[data-theme="dark"] .toast.error {
  background: #450a0a;
  color: #fca5a5;
}
.toast-enter-active { transition: all 0.3s ease; }
.toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from { opacity: 0; transform: translateY(-20px); }
.toast-leave-to { opacity: 0; transform: translateY(-20px); }

/* Metadata */
.metadata-view { margin-top: 16px; }
.metadata-view h4 { margin: 0 0 12px; }
.table-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 8px;
  overflow: hidden;
}
.table-name {
  padding: 10px 12px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.table-name:hover { background: var(--bg-tertiary); }
.col-count { font-size: 12px; color: var(--text-muted); margin-left: auto; }
.table-columns {
  border-top: 1px solid var(--border);
  padding: 8px 12px;
}
.col-header, .col-row {
  display: grid;
  grid-template-columns: 1.2fr 1fr 0.5fr 1.5fr;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}
.col-header {
  font-weight: 600;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
  margin-bottom: 4px;
}
.col-name { font-family: monospace; }
.col-type { color: var(--accent); }
.col-nullable { text-align: center; }
.col-comment { color: var(--text-muted); }

/* LLM Config */
.llm-config {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.llm-config label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}
.llm-config input, .llm-config select {
  padding: 8px;
  font-size: 13px;
}
.provider-list { margin-top: 24px; }
.provider-list h4 { margin: 0 0 8px; font-size: 13px; }
.provider-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 4px;
  cursor: pointer;
  font-size: 13px;
}
.provider-item:hover { background: var(--bg-tertiary); }
.provider-name { font-weight: 600; }
.provider-models { color: var(--text-muted); font-size: 12px; }

/* System Info */
.info-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.info-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
}
.info-label { color: var(--text-muted); }
</style>
