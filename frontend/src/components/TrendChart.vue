<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  TooltipComponent,
  LegendComponent,
  GridComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { AnalyticsTrendPoint } from '../api'

use([LineChart, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const props = defineProps<{
  data: AnalyticsTrendPoint[]
}>()

const { t } = useI18n()

type MetricKey = 'tasks' | 'changes' | 'tokens'

const activeMetric = ref<MetricKey>('tasks')

const metricPalette = {
  tasks: { tab: '#0ea5e9', primary: '#0ea5e9', secondary: '#14b8a6' },
  changes: { tab: '#14b8a6', primary: '#14b8a6', secondary: '#8b5cf6' },
  tokens: { tab: '#8b5cf6', primary: '#8b5cf6', secondary: '#0ea5e9' },
} as const

const metrics = computed<{ key: MetricKey; label: string; color: string }[]>(() => [
  { key: 'tasks', label: t('trend.tasks'), color: metricPalette.tasks.tab },
  { key: 'changes', label: t('trend.changes'), color: metricPalette.changes.tab },
  { key: 'tokens', label: t('trend.tokens'), color: metricPalette.tokens.tab },
])

const option = computed(() => {
  const d = props.data
  const dates = d.map((p) => p.date.slice(5)) // "MM-DD"

  const m = activeMetric.value

  const series: any[] = []

  if (m === 'tasks') {
    series.push(
      {
        name: t('trend.completed'),
        type: 'line',
        data: d.map((p) => p.completed_tasks),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#0ea5e9' },
        areaStyle: { color: 'rgba(14,165,233,0.10)' },
      },
      {
        name: t('trend.failed'),
        type: 'line',
        data: d.map((p) => p.failed_tasks),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#14b8a6' },
        areaStyle: { color: 'rgba(20,184,166,0.08)' },
      },
    )
  } else if (m === 'changes') {
    series.push(
      {
        name: t('trend.additions'),
        type: 'line',
        data: d.map((p) => p.additions),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#14b8a6' },
        areaStyle: { color: 'rgba(20,184,166,0.10)' },
      },
      {
        name: t('trend.deletions'),
        type: 'line',
        data: d.map((p) => p.deletions),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#8b5cf6' },
        areaStyle: { color: 'rgba(139,92,246,0.08)' },
      },
    )
  } else {
    series.push(
      {
        name: t('trend.input'),
        type: 'line',
        data: d.map((p) => p.input_tokens),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#8b5cf6' },
        areaStyle: { color: 'rgba(139,92,246,0.10)' },
      },
      {
        name: t('trend.output'),
        type: 'line',
        data: d.map((p) => p.output_tokens),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#0ea5e9' },
        areaStyle: { color: 'rgba(14,165,233,0.08)' },
      },
    )
  }

  return {
    tooltip: {
      trigger: 'axis',
      appendTo: 'body',
      textStyle: { fontSize: 12 },
      padding: [6, 10],
    },
    legend: {
      bottom: 10,
      left: 'center',
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: '#64748b' },
    },
    grid: {
      top: 8,
      left: 40,
      right: 12,
      bottom: 56,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: '#94a3b8',
        interval: Math.max(Math.floor(dates.length / 6) - 1, 0),
      },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: {
        fontSize: 10,
        color: '#94a3b8',
        formatter: (v: number) => {
          if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
          if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K'
          return String(v)
        },
      },
    },
    series,
  }
})
</script>

<template>
  <div class="trend-chart">
    <div class="trend-chart__tabs">
      <button
        v-for="m in metrics"
        :key="m.key"
        class="trend-chart__tab"
        :class="{ 'trend-chart__tab--active': activeMetric === m.key }"
        :style="activeMetric === m.key ? { color: m.color, borderBottomColor: m.color } : {}"
        @click="activeMetric = m.key"
      >
        {{ m.label }}
      </button>
    </div>
    <v-chart :option="option" autoresize class="trend-chart__chart" />
  </div>
</template>

<style scoped>
.trend-chart {
  width: 100%;
}

.trend-chart__tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.trend-chart__tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 500;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
}

.trend-chart__tab:hover {
  color: #64748b;
}

.trend-chart__tab--active {
  font-weight: 600;
}

.trend-chart__chart {
  width: 100%;
  height: 220px;
}
</style>

