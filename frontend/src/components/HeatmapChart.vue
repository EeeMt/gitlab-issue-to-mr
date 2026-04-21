<template>
  <div class="heatmap-chart">
    <!-- Legend -->
    <div class="heatmap-chart__legend">
      <span class="heatmap-chart__legend-label">Light</span>
      <div class="heatmap-chart__legend-scale">
        <span class="heatmap-chart__legend-swatch heatmap-chart__legend-swatch--1"></span>
        <span class="heatmap-chart__legend-swatch heatmap-chart__legend-swatch--2"></span>
        <span class="heatmap-chart__legend-swatch heatmap-chart__legend-swatch--3"></span>
        <span class="heatmap-chart__legend-swatch heatmap-chart__legend-swatch--4"></span>
      </div>
      <span class="heatmap-chart__legend-label">Busy</span>
      <span v-if="maxPerSlot > 0" class="heatmap-chart__legend-swatch heatmap-chart__legend-swatch--full"></span>
      <span v-if="maxPerSlot > 0" class="heatmap-chart__legend-label">Full</span>
      <span class="heatmap-chart__legend-hint">Click to select</span>
    </div>

    <!-- Grid -->
    <div
      class="heatmap-chart__grid"
      :style="{ gridTemplateColumns: `64px repeat(${heatmapDays.length}, minmax(0, 1fr))` }"
    >
      <div class="heatmap-chart__spacer"></div>
      <div v-for="day in heatmapDays" :key="day.dateKey" class="heatmap-chart__header">
        {{ day.label }}
      </div>
      <template v-for="row in heatmapRows" :key="row.hour">
        <div class="heatmap-chart__hour">{{ row.label }}</div>
        <div
          v-for="cell in row.cells"
          :key="cell.key"
          class="heatmap-chart__cell"
          :class="{
            'heatmap-chart__cell--clickable': !isCellDisabled(cell),
            'heatmap-chart__cell--disabled': isCellDisabled(cell),
            'heatmap-chart__cell--active': isCellActive(cell),
          }"
          :style="heatmapCellStyle(cell.count, heatmapMax)"
          :title="cellTooltip(cell)"
          @click="!isCellDisabled(cell) && emit('cellClick', cell.startMs)"
        >
          {{ cellDisplayText(cell.count) }}
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '../api'
import { formatMonthDayWeekdayUtc8, parseUtcDate } from '../utils/datetime'

interface Props {
  tasks: Task[]
  selectedMs?: number | null
  days?: number
  maxPerSlot?: number
  enforceCapacity?: boolean
  allowFullSelection?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  selectedMs: null,
  days: 7,
  maxPerSlot: 0,
  enforceCapacity: false,
  allowFullSelection: false,
})

const emit = defineEmits<{
  cellClick: [startMs: number]
}>()

type HeatmapDay = { dateKey: string; label: string }
type HeatmapCell = { key: string; label: string; count: number; startMs: number; endMs: number }
type HeatmapRow = { hour: number; label: string; cells: HeatmapCell[] }

const shanghaiPartsFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  hour12: false,
})

function getShanghaiParts(date: Date): Record<string, string> {
  return shanghaiPartsFormatter.formatToParts(date).reduce<Record<string, string>>((acc, part) => {
    if (part.type !== 'literal') acc[part.type] = part.value
    return acc
  }, {})
}

function getShanghaiDateKey(date: Date): string {
  const parts = getShanghaiParts(date)
  return `${parts.year}-${parts.month}-${parts.day}`
}

function buildHeatmapDays(days: number): HeatmapDay[] {
  const nowParts = getShanghaiParts(new Date())
  const baseDate = new Date(
    Date.UTC(Number(nowParts.year), Number(nowParts.month) - 1, Number(nowParts.day))
  )
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(baseDate.getTime() + index * 24 * 60 * 60 * 1000)
    const year = date.getUTCFullYear()
    const month = String(date.getUTCMonth() + 1).padStart(2, '0')
    const day = String(date.getUTCDate()).padStart(2, '0')
    return {
      dateKey: `${year}-${month}-${day}`,
      label: formatMonthDayWeekdayUtc8(date),
    }
  })
}

const heatmapDays = computed(() => buildHeatmapDays(props.days ?? 7))

const heatmapRows = computed<HeatmapRow[]>(() => {
  const dayKeys = heatmapDays.value.map((day) => day.dateKey)
  const counts = new Map<string, number>()
  props.tasks.forEach((task) => {
    if (!task.scheduled_at) return
    const scheduledDate = parseUtcDate(task.scheduled_at)
    const dateKey = getShanghaiDateKey(scheduledDate)
    if (!dayKeys.includes(dateKey)) return
    const parts = getShanghaiParts(scheduledDate)
    const hour = Number(parts.hour)
    const key = `${dateKey}-${hour}`
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return Array.from({ length: 24 }, (_, hour) => ({
    hour,
    label: `${String(hour).padStart(2, '0')}:00`,
    cells: heatmapDays.value.map((day) => {
      const key = `${day.dateKey}-${hour}`
      const startMs = new Date(
        `${day.dateKey}T${String(hour).padStart(2, '0')}:00:00+08:00`
      ).getTime()
      return {
        key,
        label: `${day.label} ${String(hour).padStart(2, '0')}:00`,
        count: counts.get(key) || 0,
        startMs,
        endMs: startMs + 60 * 60 * 1000,
      }
    }),
  }))
})

const heatmapMax = computed(() =>
  heatmapRows.value.reduce((max, row) => Math.max(max, ...row.cells.map((c) => c.count)), 0)
)

function heatmapCellStyle(count: number, maxCount: number) {
  if (count === 0 || maxCount === 0) {
    return { background: 'rgba(148, 163, 184, 0.12)', color: 'rgba(15, 23, 42, 0.45)' }
  }
  // Full slot → red
  if (props.maxPerSlot > 0 && count >= props.maxPerSlot) {
    return { background: 'rgba(220, 38, 38, 0.65)', color: '#fff' }
  }
  const intensity = count / maxCount
  const alpha = 0.18 + intensity * 0.52
  return {
    background: `rgba(32, 128, 240, ${alpha.toFixed(3)})`,
    color: intensity > 0.58 ? '#fff' : '#0f172a',
  }
}

function cellDisplayText(count: number): string {
  if (count === 0) return ''
  return String(count)
}

function cellTooltip(cell: HeatmapCell): string {
  const countText = props.maxPerSlot > 0
    ? `${cell.count}/${props.maxPerSlot}`
    : `${cell.count}`
  return `${cell.label}: ${countText} task${cell.count !== 1 ? 's' : ''}`
}

function isCellFull(cell: HeatmapCell): boolean {
  return props.maxPerSlot > 0 && cell.count >= props.maxPerSlot
}

function isCellDisabled(cell: HeatmapCell): boolean {
  return props.enforceCapacity && !props.allowFullSelection && isCellFull(cell)
}

function isCellActive(cell: HeatmapCell): boolean {
  if (props.selectedMs == null) return false
  return props.selectedMs >= cell.startMs && props.selectedMs < cell.endMs
}
</script>

<style scoped>
.heatmap-chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.heatmap-chart__legend {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.heatmap-chart__legend-scale {
  display: flex;
  gap: 6px;
}

.heatmap-chart__legend-swatch {
  width: 16px;
  height: 10px;
  border-radius: 999px;
}

.heatmap-chart__legend-swatch--1 { background: rgba(32, 128, 240, 0.2); }
.heatmap-chart__legend-swatch--2 { background: rgba(32, 128, 240, 0.34); }
.heatmap-chart__legend-swatch--3 { background: rgba(32, 128, 240, 0.5); }
.heatmap-chart__legend-swatch--4 { background: rgba(32, 128, 240, 0.68); }
.heatmap-chart__legend-swatch--full { background: rgba(220, 38, 38, 0.65); }

.heatmap-chart__legend-hint {
  font-size: 11px;
  background: rgba(32, 128, 240, 0.08);
  border: 1px solid rgba(32, 128, 240, 0.18);
  border-radius: 4px;
  padding: 1px 6px;
  color: rgba(32, 128, 240, 0.85);
}

.heatmap-chart__grid {
  display: grid;
  gap: 8px;
  align-items: center;
}

.heatmap-chart__header {
  text-align: center;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.64);
}

.heatmap-chart__spacer {
  visibility: hidden;
}

.heatmap-chart__hour {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.heatmap-chart__cell {
  min-height: 30px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.heatmap-chart__cell--clickable {
  cursor: pointer;
}

.heatmap-chart__cell--disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.heatmap-chart__cell--clickable:not(.heatmap-chart__cell--active):hover {
  transform: translateY(-1px);
  box-shadow: inset 0 0 0 1px rgba(32, 128, 240, 0.22);
}

.heatmap-chart__cell--active {
  box-shadow: inset 0 0 0 2px rgba(15, 23, 42, 0.32), 0 0 0 2px rgba(24, 160, 88, 0.4);
  outline: 2px solid rgba(24, 160, 88, 0.6);
  outline-offset: 1px;
}

.heatmap-chart__cell--active:hover {
  transform: none;
  box-shadow: inset 0 0 0 2px rgba(15, 23, 42, 0.32), 0 0 0 2px rgba(24, 160, 88, 0.4);
}

@media (max-width: 768px) {
  .heatmap-chart__grid {
    grid-template-columns: 54px repeat(7, minmax(44px, 1fr)) !important;
    gap: 6px;
    overflow-x: auto;
  }

  .heatmap-chart__cell {
    min-height: 28px;
    font-size: 11px;
  }
}
</style>
