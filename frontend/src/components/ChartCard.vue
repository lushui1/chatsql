<template>
  <div class="chart-card" v-if="args">
    <div class="chart-header">
      <h3 class="chart-title">{{ args.chart?.title || '图表' }}</h3>
      <span class="chart-type">{{ args.chart?.type || '' }}</span>
    </div>

    <!-- Chart -->
    <div class="chart-container" ref="chartRef" v-if="args.chart && args.data"></div>

    <!-- SQL -->
    <details class="sql-details" v-if="args.sql">
      <summary>查看SQL</summary>
      <pre class="sql-code">{{ args.sql }}</pre>
    </details>

    <!-- Answer -->
    <p class="chart-answer" v-if="args.chart_answer">{{ args.chart_answer }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, LineChart, PieChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ args: any }>()
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

onMounted(() => {
  renderChart()
})

watch(() => props.args, () => {
  nextTick(() => renderChart())
}, { deep: true })

function renderChart() {
  if (!chartRef.value || !props.args?.chart || !props.args?.data) return

  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const { chart: chartCfg, data } = props.args
  const columns = data.columns?.map((c: any) => c.name) || []
  const rows = data.rows || []

  let option: any = {}

  if (chartCfg.type === 'pie') {
    option = {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: '#9ca3af' } },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        data: rows.map((r: any) => ({ name: r[chartCfg.x], value: r[chartCfg.y] })),
      }],
    }
  } else {
    const xData = rows.map((r: any) => r[chartCfg.x])
    const yData = rows.map((r: any) => r[chartCfg.y])
    option = {
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: xData,
        axisLabel: { color: '#9ca3af' },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#9ca3af' },
      },
      series: [{
        type: chartCfg.type === 'line' ? 'line' : 'bar',
        data: yData,
        smooth: chartCfg.type === 'line',
        itemStyle: { color: '#3b82f6' },
      }],
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    }
  }

  chart.setOption(option)
}
</script>

<style scoped>
.chart-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.chart-title {
  font-size: 15px;
  font-weight: 600;
}
.chart-type {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-tertiary);
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}
.chart-container {
  width: 100%;
  height: 300px;
}
.sql-details {
  margin-top: 12px;
}
.sql-details summary {
  cursor: pointer;
  color: var(--text-muted);
  font-size: 13px;
}
.sql-code {
  margin-top: 8px;
  background: var(--bg-primary);
  padding: 12px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12px;
  overflow-x: auto;
  color: var(--text-secondary);
}
.chart-answer {
  margin-top: 12px;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
