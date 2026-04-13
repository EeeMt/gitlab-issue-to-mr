<script setup lang="ts">
import { computed, ref } from 'vue'
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

type MetricKey = 'tasks' | 'changes' | 'tokens'

const activeMetric = ref<MetricKey>('tasks')

const metrics: { key: MetricKey; label: string; color: string }[] = [
  { key: 'tasks', label: 'Tasks', color: '#2080f0' },
  { key: 'changes', label: 'Changes', color: '#18a058' },
  { key: 'tokens', label: 'Tokens', color: '#f0a020' },
]

const option = computed(() => {
  const d = props.data
  const dates = d.map((p) => p.date.slice(5)) // "MM-DD"

  const m = activeMetric.value

  const series: any[] = []

  if (m === 'tasks') {
    series.push(
      {
        name: 'Completed',
        type: 'line',
        data: d.map((p) => p.completed_tasks),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#18a058' },
        areaStyle: { color: 'rgba(24,160,88,0.08)' },
      },
      {
        name: 'Failed',
        type: 'line',
        data: d.map((p) => p.failed_tasks),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#d03050' },
        areaStyle: { color: 'rgba(208,48,80,0.06)' },
      },
    )
  } else if (m === 'changes') {
    series.push(
      {
        name: 'Additions',
        type: 'line',
        data: d.map((p) => p.additions),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#18a058' },
        areaStyle: { color: 'rgba(24,160,88,0.08)' },
      },
      {
        name: 'Deletions',
        type: 'line',
        data: d.map((p) => p.deletions),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#d03050' },
        areaStyle: { color: 'rgba(208,48,80,0.06)' },
      },
    )
  } else {
    series.push(
      {
        name: 'Input',
        type: 'line',
        data: d.map((p) => p.input_tokens),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#2080f0' },
        areaStyle: { color: 'rgba(32,128,240,0.08)' },
      },
      {
        name: 'Output',
        type: 'line',
        data: d.map((p) => p.output_tokens),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
        itemStyle: { color: '#f0a020' },
        areaStyle: { color: 'rgba(240,160,32,0.06)' },
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
      bottom: 0,
      left: 'center',
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: '#666' },
    },
    grid: {
      top: 8,
      left: 40,
      right: 12,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: '#999',
        interval: Math.max(Math.floor(dates.length / 6) - 1, 0),
      },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#f0f0f0' } },
      axisLabel: {
        fontSize: 10,
        color: '#999',
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
  color: #999;
  cursor: pointer;
  transition: all 0.2s;
}

.trend-chart__tab:hover {
  color: #666;
}

.trend-chart__tab--active {
  font-weight: 600;
}

.trend-chart__chart {
  width: 100%;
  height: 200px;
}
</style>
