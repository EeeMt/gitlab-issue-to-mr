<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  data: { name: string; value: number; color: string }[]
}>()

const option = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: '{b}: {c} ({d}%)',
    appendTo: 'body',
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
      center: ['50%', '45%'],
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
  <v-chart :option="option" autoresize class="status-pie-chart" />
</template>

<style scoped>
.status-pie-chart {
  width: 100%;
  height: 170px;
}
</style>
