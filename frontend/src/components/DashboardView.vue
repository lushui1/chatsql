<template>
  <div class="dashboard-view">
    <!-- 仪表盘列表 -->
    <div v-if="!selectedDashboard" class="dashboard-list">
      <div class="view-header">
        <h2>📊 仪表盘</h2>
        <button class="btn-primary" @click="createDashboard">+ 新建仪表盘</button>
      </div>
      <div class="dashboard-grid">
        <div
          v-for="d in dashboards"
          :key="d.id"
          class="dashboard-card"
          @click="selectDashboard(d)"
        >
          <div class="card-preview">
            <div v-for="c in (d.charts || []).slice(0, 3)" :key="c.id" class="mini-chart">
              <div class="mini-chart-placeholder">📊</div>
            </div>
            <div v-if="!d.charts?.length" class="empty-preview">暂无图表</div>
          </div>
          <div class="card-info">
            <h3>{{ d.name }}</h3>
            <span>{{ d.charts?.length || 0 }} 个图表</span>
          </div>
        </div>
        <div v-if="dashboards.length === 0" class="empty-state">
          <p>暂无仪表盘</p>
          <p class="empty-hint">点击上方按钮创建第一个仪表盘</p>
        </div>
      </div>
    </div>

    <!-- 仪表盘详情 -->
    <div v-else class="dashboard-detail">
      <div class="detail-header">
        <button class="btn-back" @click="selectedDashboard = null">← 返回</button>
        <h2>{{ selectedDashboard.name }}</h2>
      </div>
      <div class="charts-grid">
        <div v-for="chart in selectedDashboard.charts" :key="chart.id" class="chart-cell">
          <div class="chart-cell-content">
            <div class="chart-cell-header">
              <span>{{ chart.config?.chart?.title || '图表' }}</span>
              <span class="chart-type-badge">{{ chart.config?.chart?.type || '' }}</span>
            </div>
            <div class="chart-cell-body">
              <ChartCard :args="chart.config" />
            </div>
          </div>
        </div>
        <div v-if="!selectedDashboard.charts?.length" class="empty-charts">
          <p>暂无图表</p>
          <p class="empty-hint">在对话中生成图表后，可保存到此仪表盘</p>
        </div>
      </div>
    </div>

    <!-- 新建仪表盘对话框 -->
    <div v-if="showCreateDialog" class="dialog-overlay" @click.self="showCreateDialog = false">
      <div class="dialog">
        <h3>新建仪表盘</h3>
        <input v-model="newDashboardName" placeholder="仪表盘名称" @keydown.enter="confirmCreate" />
        <div class="dialog-actions">
          <button class="btn-cancel" @click="showCreateDialog = false">取消</button>
          <button class="btn-primary" @click="confirmCreate" :disabled="!newDashboardName.trim()">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import ChartCard from './ChartCard.vue'

interface DashboardChart {
  id: string
  config: any
}

interface Dashboard {
  id: string
  name: string
  charts: DashboardChart[]
  created_at: string
  updated_at: string
}

const API = '/v1'

const dashboards = ref<Dashboard[]>([])
const selectedDashboard = ref<Dashboard | null>(null)
const showCreateDialog = ref(false)
const newDashboardName = ref('')

onMounted(() => {
  loadDashboards()
})

async function loadDashboards() {
  try {
    const res = await fetch(`${API}/dashboards`)
    if (res.ok) {
      dashboards.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to load dashboards', e)
  }
}

async function createDashboard() {
  newDashboardName.value = ''
  showCreateDialog.value = true
}

async function confirmCreate() {
  const name = newDashboardName.value.trim()
  if (!name) return

  try {
    const res = await fetch(`${API}/dashboards`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (res.ok) {
      const d = await res.json()
      dashboards.value.push(d)
      showCreateDialog.value = false
      selectedDashboard.value = d
    }
  } catch (e) {
    console.error('Failed to create dashboard', e)
  }
}

async function selectDashboard(d: Dashboard) {
  try {
    const res = await fetch(`${API}/dashboards/${d.id}`)
    if (res.ok) {
      selectedDashboard.value = await res.json()
    } else {
      selectedDashboard.value = d
    }
  } catch {
    selectedDashboard.value = d
  }
}
</script>

<style scoped>
.dashboard-view {
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.view-header h2 {
  margin: 0;
  font-size: 20px;
}

.btn-primary {
  background: var(--accent);
  color: white;
  border: none;
  padding: 8px 20px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Dashboard grid */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.dashboard-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s;
  overflow: hidden;
}

.dashboard-card:hover {
  border-color: var(--accent);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
  transform: translateY(-2px);
}

.card-preview {
  height: 140px;
  background: var(--bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px;
}

.mini-chart {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mini-chart-placeholder {
  font-size: 32px;
  opacity: 0.3;
}

.empty-preview {
  color: var(--text-muted);
  font-size: 14px;
}

.card-info {
  padding: 14px 16px;
}

.card-info h3 {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
}

.card-info span {
  font-size: 12px;
  color: var(--text-muted);
}

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 48px;
  color: var(--text-muted);
}

.empty-hint {
  font-size: 13px;
  margin-top: 4px;
}

/* Dashboard detail */
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.detail-header h2 {
  margin: 0;
  font-size: 20px;
}

.btn-back {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  padding: 6px 14px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.btn-back:hover {
  background: var(--bg-hover);
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
}

.chart-cell {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.chart-cell-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
}

.chart-type-badge {
  font-size: 11px;
  background: var(--bg-tertiary);
  padding: 2px 8px;
  border-radius: 4px;
  color: var(--text-muted);
  text-transform: uppercase;
}

.chart-cell-body {
  padding: 12px;
}

.empty-charts {
  grid-column: 1 / -1;
  text-align: center;
  padding: 48px;
  color: var(--text-muted);
}

/* Dialog */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  width: 400px;
  max-width: 90vw;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.dialog h3 {
  margin: 0 0 16px;
  font-size: 16px;
}

.dialog input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 14px;
  margin-bottom: 16px;
}

.dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.btn-cancel {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  padding: 8px 20px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 14px;
}
</style>
