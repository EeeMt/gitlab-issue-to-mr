import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import HeatmapChart from './HeatmapChart.vue'

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../utils/datetime', () => ({
  formatMonthDayWeekdayUtc8: vi.fn(() => 'Mon 01/01'),
  parseUtcDate: vi.fn((v: string) => new Date(v))
}))

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('HeatmapChart', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  const mountComponent = (props: Record<string, any> = {}) =>
    mount(HeatmapChart, {
      props: {
        tasks: [],
        ...props
      }
    })

  // -------------------------------------------------------------------------
  // Default behavior (maxPerSlot = 0)
  // -------------------------------------------------------------------------
  describe('default behavior (maxPerSlot = 0)', () => {
    it('renders without maxPerSlot prop', () => {
      wrapper = mountComponent()
      expect(wrapper.find('.heatmap-chart').exists()).toBe(true)
      expect(wrapper.find('.heatmap-chart__grid').exists()).toBe(true)
    })

    it('"Full" legend swatch is hidden when maxPerSlot = 0', () => {
      wrapper = mountComponent()
      expect(wrapper.find('.heatmap-chart__legend-swatch--full').exists()).toBe(false)
    })

    it('"Full" label text does not appear in legend', () => {
      wrapper = mountComponent()
      const legendLabels = wrapper.findAll('.heatmap-chart__legend-label')
      expect(legendLabels.some(el => el.text() === 'Full')).toBe(false)
    })

    it('cell text shows plain count when maxPerSlot = 0', () => {
      wrapper = mountComponent()
      expect(wrapper.vm.cellDisplayText(3)).toBe('3')
      expect(wrapper.vm.cellDisplayText(10)).toBe('10')
    })

    it('cellDisplayText returns empty string for zero count', () => {
      wrapper = mountComponent()
      expect(wrapper.vm.cellDisplayText(0)).toBe('')
    })

    it('cellTooltip shows plain count format', () => {
      wrapper = mountComponent()
      const cell = { key: 'k', label: 'Mon 10:00', count: 3, startMs: 0, endMs: 0 }
      expect(wrapper.vm.cellTooltip(cell)).toBe('Mon 10:00: 3 tasks')
    })

    it('cellTooltip uses singular "task" for count 1', () => {
      wrapper = mountComponent()
      const cell = { key: 'k', label: 'Mon 10:00', count: 1, startMs: 0, endMs: 0 }
      expect(wrapper.vm.cellTooltip(cell)).toBe('Mon 10:00: 1 task')
    })

    it('heatmapCellStyle returns blue background for non-zero count', () => {
      wrapper = mountComponent()
      const style = wrapper.vm.heatmapCellStyle(3, 5)
      expect(style.background).toContain('rgba(32, 128, 240,')
    })

    it('heatmapCellStyle returns muted background for zero count', () => {
      wrapper = mountComponent()
      const style = wrapper.vm.heatmapCellStyle(0, 5)
      expect(style.background).toBe('rgba(148, 163, 184, 0.12)')
    })

    it('heatmapCellStyle returns muted background when maxCount is zero', () => {
      wrapper = mountComponent()
      const style = wrapper.vm.heatmapCellStyle(0, 0)
      expect(style.background).toBe('rgba(148, 163, 184, 0.12)')
    })
  })

  // -------------------------------------------------------------------------
  // With maxPerSlot > 0
  // -------------------------------------------------------------------------
  describe('with maxPerSlot > 0', () => {
    it('"Full" legend swatch appears when maxPerSlot > 0', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      expect(wrapper.find('.heatmap-chart__legend-swatch--full').exists()).toBe(true)
    })

    it('"Full" label text appears in legend', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      const legendLabels = wrapper.findAll('.heatmap-chart__legend-label')
      expect(legendLabels.some(el => el.text() === 'Full')).toBe(true)
    })

    it('cell text still shows plain count when maxPerSlot > 0', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      expect(wrapper.vm.cellDisplayText(3)).toBe('3')
      expect(wrapper.vm.cellDisplayText(5)).toBe('5')
    })

    it('cellDisplayText still returns empty for zero count with maxPerSlot', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      expect(wrapper.vm.cellDisplayText(0)).toBe('')
    })

    it('cellTooltip returns count/max format', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      const cell = { key: 'k', label: 'Mon 10:00', count: 3, startMs: 0, endMs: 0 }
      expect(wrapper.vm.cellTooltip(cell)).toBe('Mon 10:00: 3/5 tasks')
    })

    it('cellTooltip singular with count/max format', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      const cell = { key: 'k', label: 'Mon 10:00', count: 1, startMs: 0, endMs: 0 }
      expect(wrapper.vm.cellTooltip(cell)).toBe('Mon 10:00: 1/5 task')
    })

    it('isCellDisabled blocks full slots when capacity is enforced', () => {
      wrapper = mountComponent({ maxPerSlot: 5, enforceCapacity: true })
      const cell = { key: 'k', label: 'Mon 10:00', count: 5, startMs: 0, endMs: 0 }
      expect(wrapper.vm.isCellDisabled(cell)).toBe(true)
    })

    it('isCellDisabled allows full-slot selection when opted in', () => {
      wrapper = mountComponent({ maxPerSlot: 5, enforceCapacity: true, allowFullSelection: true })
      const cell = { key: 'k', label: 'Mon 10:00', count: 5, startMs: 0, endMs: 0 }
      expect(wrapper.vm.isCellDisabled(cell)).toBe(false)
    })

    it('heatmapCellStyle returns red background when count >= maxPerSlot (exact)', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      const style = wrapper.vm.heatmapCellStyle(5, 10)
      expect(style.background).toBe('rgba(220, 38, 38, 0.65)')
      expect(style.color).toBe('#fff')
    })

    it('heatmapCellStyle returns red background when count exceeds maxPerSlot', () => {
      wrapper = mountComponent({ maxPerSlot: 3 })
      const style = wrapper.vm.heatmapCellStyle(7, 10)
      expect(style.background).toBe('rgba(220, 38, 38, 0.65)')
      expect(style.color).toBe('#fff')
    })

    it('heatmapCellStyle returns blue background when count < maxPerSlot', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      const style = wrapper.vm.heatmapCellStyle(3, 5)
      expect(style.background).toContain('rgba(32, 128, 240,')
    })

    it('heatmapCellStyle returns muted background for zero count even with maxPerSlot', () => {
      wrapper = mountComponent({ maxPerSlot: 5 })
      const style = wrapper.vm.heatmapCellStyle(0, 5)
      expect(style.background).toBe('rgba(148, 163, 184, 0.12)')
    })
  })

  // -------------------------------------------------------------------------
  // Cell active state
  // -------------------------------------------------------------------------
  describe('cell active state', () => {
    it('isCellActive returns false when selectedMs is null', () => {
      wrapper = mountComponent({ selectedMs: null })
      const cell = { key: 'k', label: 'L', count: 0, startMs: 1000, endMs: 2000 }
      expect(wrapper.vm.isCellActive(cell)).toBe(false)
    })

    it('isCellActive returns true when selectedMs is within cell range', () => {
      wrapper = mountComponent({ selectedMs: 1500 })
      const cell = { key: 'k', label: 'L', count: 0, startMs: 1000, endMs: 2000 }
      expect(wrapper.vm.isCellActive(cell)).toBe(true)
    })

    it('isCellActive returns false when selectedMs is outside cell range', () => {
      wrapper = mountComponent({ selectedMs: 3000 })
      const cell = { key: 'k', label: 'L', count: 0, startMs: 1000, endMs: 2000 }
      expect(wrapper.vm.isCellActive(cell)).toBe(false)
    })
  })

  // -------------------------------------------------------------------------
  // Emit
  // -------------------------------------------------------------------------
  describe('cellClick emit', () => {
    it('emits cellClick with startMs when a cell is clicked', async () => {
      wrapper = mountComponent()
      const cells = wrapper.findAll('.heatmap-chart__cell')
      if (cells.length > 0) {
        await cells[0].trigger('click')
        expect(wrapper.emitted('cellClick')).toBeTruthy()
        expect(wrapper.emitted('cellClick')![0]).toHaveLength(1)
      }
    })
  })
})
