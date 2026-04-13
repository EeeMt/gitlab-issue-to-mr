<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  title: string
  data: { name: string; value: number; color: string }[]
}>()

const option = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: '{b}: {c} ({d}%)',
  },
  legend: {
    bottom: 0,
    left: 'center',
    itemWidth: 10,
    itemHeight: 10,
    textStyle: { fontSize: 11, color: '#666' },
  },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '42%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      emphasis: {
        label: { show: true, fontSize: 13, fontWeight: 'bold' },
      },
      data: props.data.map((d) => ({
        name: d.name,
        value: d.value,
        itemStyle: { color: d.color },
      })),
    },
  ],
}))
</script>

<template>
  <div class="status-pie">
    <div class="status-pie__title">{{ title }}</div>
    <v-chart :option="option" autoresize class="status-pie__chart" />
  </div>
</template>

<style scoped>
.status-pie {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.status-pie__title {
  font-size: 13px;
  font-weight: 600;
  color: #666;
  margin-bottom: 4px;
  text-align: center;
}

.status-pie__chart {
  flex: 1;
  min-height: 160px;
}
</style>
