<template>
  <div class="activity-heatmap" data-testid="activity-heatmap">
    <div class="activity-heatmap__wrapper">
      <!-- Row 1: month labels (above cells, offset by day-label width) -->
      <div class="activity-heatmap__months" :style="{ gridTemplateColumns: `repeat(${weeks.length}, 13px)` }">
        <span
          v-for="m in monthLabels"
          :key="m.key"
          class="activity-heatmap__month-label"
          :style="{ gridColumnStart: m.col }"
        >{{ m.label }}</span>
      </div>
      <!-- Row 2: day labels + cell grid -->
      <div class="activity-heatmap__body">
        <div class="activity-heatmap__days">
          <span class="activity-heatmap__day-label">{{ t('common.mon') }}</span>
          <span class="activity-heatmap__day-label"></span>
          <span class="activity-heatmap__day-label">{{ t('common.wed') }}</span>
          <span class="activity-heatmap__day-label"></span>
          <span class="activity-heatmap__day-label">{{ t('common.fri') }}</span>
          <span class="activity-heatmap__day-label"></span>
          <span class="activity-heatmap__day-label"></span>
        </div>
        <div class="activity-heatmap__cells" :style="{ gridTemplateColumns: `repeat(${weeks.length}, 13px)` }">
          <template v-for="(week, wi) in weeks" :key="wi">
            <div
              v-for="(day, di) in week"
              :key="`${wi}-${di}`"
              class="activity-heatmap__cell"
              :class="day ? `activity-heatmap__cell--level-${getLevel(day.count)}` : 'activity-heatmap__cell--empty'"
              :title="day ? `${day.count} ${day.count === 1 ? 'task' : 'tasks'} on ${day.date}` : ''"
              :style="{ gridRow: di + 1, gridColumn: wi + 1 }"
            />
          </template>
        </div>
      </div>
    </div>
    <div class="activity-heatmap__legend">
      <span class="activity-heatmap__legend-label">{{ t('common.less') }}</span>
      <div class="activity-heatmap__cell activity-heatmap__cell--level-0" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-1" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-2" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-3" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-4" />
      <span class="activity-heatmap__legend-label">{{ t('common.more') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ActivityHeatmapEntry } from '../api'

const { t } = useI18n()

const props = defineProps<{
  data: ActivityHeatmapEntry[]
}>()

interface DayCell {
  date: string
  count: number
}

const countMap = computed(() => {
  const map = new Map<string, number>()
  for (const entry of props.data) {
    map.set(entry.date, entry.count)
  }
  return map
})

const weeks = computed(() => {
  const result: (DayCell | null)[][] = []
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  // Find the start: go back ~52 weeks to the nearest Sunday
  const dayOfWeek = today.getDay() // 0=Sun
  const daysBack = 364 + dayOfWeek
  const start = new Date(today)
  start.setDate(start.getDate() - daysBack)

  let currentWeek: (DayCell | null)[] = []
  const d = new Date(start)

  while (d <= today) {
    const dateStr = d.toISOString().slice(0, 10)
    const count = countMap.value.get(dateStr) ?? 0
    currentWeek.push({ date: dateStr, count })

    if (currentWeek.length === 7) {
      result.push(currentWeek)
      currentWeek = []
    }
    d.setDate(d.getDate() + 1)
  }

  // Pad the last week
  if (currentWeek.length > 0) {
    while (currentWeek.length < 7) {
      currentWeek.push(null)
    }
    result.push(currentWeek)
  }

  return result
})

const monthLabels = computed(() => {
  const labels: { key: string; label: string; col: number }[] = []
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  let lastMonth = -1

  for (let wi = 0; wi < weeks.value.length; wi++) {
    const firstDay = weeks.value[wi].find(d => d !== null)
    if (!firstDay) continue
    const month = new Date(firstDay.date).getMonth()
    if (month !== lastMonth) {
      labels.push({ key: `${wi}-${month}`, label: monthNames[month], col: wi + 1 })
      lastMonth = month
    }
  }
  return labels
})

function getLevel(count: number): number {
  if (count === 0) return 0
  if (count <= 2) return 1
  if (count <= 4) return 2
  if (count <= 6) return 3
  return 4
}
</script>

<style scoped>
.activity-heatmap__wrapper {
  overflow-x: auto;
}

.activity-heatmap__months {
  display: grid;
  grid-template-rows: 1fr;
  font-size: 10px;
  color: var(--n-text-color-3);
  margin-bottom: 4px;
  margin-left: 32px;
  gap: 2px;
}

.activity-heatmap__month-label {
  white-space: nowrap;
}

.activity-heatmap__body {
  display: flex;
  gap: 4px;
}

.activity-heatmap__days {
  display: flex;
  flex-direction: column;
  gap: 2px;
  justify-content: flex-start;
}

.activity-heatmap__day-label {
  height: 11px;
  font-size: 9px;
  line-height: 11px;
  color: var(--n-text-color-3);
  text-align: right;
  min-width: 24px;
}

.activity-heatmap__cells {
  display: grid;
  grid-template-rows: repeat(7, 11px);
  gap: 2px;
}

.activity-heatmap__cell {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  transition: outline 0.15s ease;
}

.activity-heatmap__cell:hover:not(.activity-heatmap__cell--empty) {
  outline: 2px solid rgba(255, 255, 255, 0.6);
  outline-offset: -1px;
}

.activity-heatmap__cell--empty {
  background: transparent;
}

.activity-heatmap__cell--level-0 {
  background: var(--n-border-color);
}

.activity-heatmap__cell--level-1 {
  background: #9be9a8;
}

.activity-heatmap__cell--level-2 {
  background: #40c463;
}

.activity-heatmap__cell--level-3 {
  background: #30a14e;
}

.activity-heatmap__cell--level-4 {
  background: #216e39;
}

.activity-heatmap__legend {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 8px;
  justify-content: flex-end;
}

.activity-heatmap__legend-label {
  font-size: 10px;
  color: var(--n-text-color-3);
  margin: 0 2px;
}
</style>
