<template>
  <n-card
    class="my-work-board"
    :bordered="false"
    data-testid="dashboard-my-work-board"
    :header-style="{ paddingBottom: '6px' }"
  >
    <template #header>
      <div class="my-work-board__header">
        <div class="my-work-board__header-meta">
          <span class="my-work-board__title">{{ t('dashboard.myWorkBoard.title') }}</span>
          <span
            v-if="hasMoreItems"
            class="my-work-board__header-notice"
            :data-testid="`my-work-board-notice-${activeTab}`"
          >
            {{ t('dashboard.myWorkBoard.limitNotice', { shown: visibleLimit, total: activeTotal }) }}
          </span>
        </div>
        <div class="my-work-board__tabs">
          <button
            type="button"
            data-testid="my-work-board-tab-issues"
            data-tab-value="issues"
            :data-active="String(activeTab === 'issues')"
            class="my-work-board__tab-button"
            @click="activeTab = 'issues'"
          >
            {{ t('common.issues') }}
          </button>
          <button
            type="button"
            data-testid="my-work-board-tab-tasks"
            data-tab-value="tasks"
            :data-active="String(activeTab === 'tasks')"
            class="my-work-board__tab-button"
            @click="activeTab = 'tasks'"
          >
            {{ t('common.tasks') }}
          </button>
        </div>
      </div>
    </template>

    <div
      class="my-work-board__panel"
      :class="{ 'my-work-board__panel--mobile': isMobile }"
      data-testid="my-work-board-panel"
    >

      <div
        v-if="activeColumns.every((column) => column.items.length === 0)"
        :data-testid="`my-work-board-empty-${activeTab}`"
        class="my-work-board__empty"
      >
        {{ t('dashboard.myWorkBoard.emptyBoard') }}
      </div>

      <n-scrollbar
        v-else
        :x-scrollable="!isMobile"
        trigger="hover"
        class="my-work-board__columns-scrollbar"
        :class="{ 'my-work-board__columns-scrollbar--mobile': isMobile }"
        :content-style="!isMobile ? 'height: 100%; padding-bottom: 8px;' : 'padding-bottom: 8px;'"
      >
        <div
          class="my-work-board__columns"
          :class="{ 'my-work-board__columns--mobile': isMobile }"
          :style="boardColumnsStyle"
        >
        <section
          v-for="column in activeColumns"
          :key="`${activeTab}-${column.status}`"
          class="my-work-board__column my-work-board__column--board"
          :data-testid="`${activeTab === 'issues' ? 'issue' : 'task'}-column-${column.status}`"
        >
          <header class="my-work-board__column-header">
            <div class="my-work-board__column-title">
              <n-icon size="14" class="my-work-board__column-icon">
                <component :is="getColumnIcon(column.status)" />
              </n-icon>
              <span>{{ column.label }}</span>
            </div>
            <span>{{ column.count }}</span>
          </header>

          <n-scrollbar class="my-work-board__column-body-scrollbar" trigger="hover" content-style="padding-right: 12px; padding-bottom: 2px;">
            <div class="my-work-board__column-body">
              <button
                v-for="item in column.items"
                :key="item.id"
                type="button"
                class="my-work-board__card"
              :class="{ 'my-work-board__card--task': activeTab === 'tasks' }"
              :data-testid="`${activeTab === 'issues' ? 'issue' : 'task'}-card-${item.id}`"
                :title="item.fullTitle || item.title"
                @click="emit('select', item.route)"
              >
                <div class="my-work-board__card-title">{{ item.title }}</div>
                <div class="my-work-board__card-subtitle">
                  {{ item.subtitle }}
                  <span v-if="item.badge" class="my-work-board__card-badge">{{ item.badge }}</span>
                </div>
                <div class="my-work-board__card-meta">{{ item.meta.join(' · ') }}</div>
              </button>

              <div v-if="column.items.length === 0" class="my-work-board__column-empty">
                {{ t('dashboard.myWorkBoard.emptyColumn') }}
              </div>
            </div>
            <div
              v-if="column.viewMoreRoute && column.count > column.items.length"
              class="my-work-board__column-view-more"
            >
              <n-button
                text
                size="tiny"
                :data-testid="`my-work-board-view-more-${activeTab}-${column.status}`"
                @click="emit('viewMore', column.viewMoreRoute!)"
              >
                {{ t('dashboard.myWorkBoard.viewMore') }}
              </n-button>
            </div>
          </n-scrollbar>
        </section>
      </div>
      </n-scrollbar>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NCard, NIcon, NButton, NScrollbar } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  CheckmarkCircleOutline,
  CloseCircleOutline,
  EllipseOutline,
  PauseCircleOutline,
  PlayCircleOutline,
  SearchOutline,
} from '@vicons/ionicons5'

export type BoardKind = 'issues' | 'tasks'

export interface BoardCardItem {
  id: number
  title: string
  fullTitle?: string
  subtitle: string
  badge?: string
  meta: string[]
  route: string
}

export interface BoardColumn {
  status: string
  label: string
  count: number
  items: BoardCardItem[]
  viewMoreRoute?: string
}

const props = defineProps<{
  issueColumns: BoardColumn[]
  taskColumns: BoardColumn[]
  issueTotal: number
  taskTotal: number
  visibleLimit: number
  isMobile: boolean
}>()

const emit = defineEmits<{
  select: [route: string]
  viewMore: [route: string]
}>()

const { t } = useI18n()
const activeTab = ref<BoardKind>('issues')

const columnIcons = {
  open: EllipseOutline,
  in_progress: PlayCircleOutline,
  in_review: SearchOutline,
  closed: CheckmarkCircleOutline,
  pending: PauseCircleOutline,
  running: PlayCircleOutline,
  completed: CheckmarkCircleOutline,
  failed: CloseCircleOutline,
} as const

const activeColumns = computed(() =>
  activeTab.value === 'issues' ? props.issueColumns : props.taskColumns,
)

const activeTotal = computed(() =>
  activeTab.value === 'issues' ? props.issueTotal : props.taskTotal,
)

const hasMoreItems = computed(() => activeTotal.value > props.visibleLimit)
const boardColumnsStyle = computed(() => {
  const columnCount = activeColumns.value.length
  const desktopMinWidth = columnCount * 220 + Math.max(columnCount - 1, 0) * 12
  return {
    '--my-work-board-column-count': String(columnCount),
    minWidth: props.isMobile ? '100%' : `${desktopMinWidth}px`,
    ...(props.isMobile ? {} : { height: '100%' }),
  }
})

function getColumnIcon(status: string) {
  return columnIcons[status as keyof typeof columnIcons] ?? EllipseOutline
}
</script>

<style scoped>
.my-work-board {
  border-radius: var(--app-card-radius);
}

.my-work-board__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.my-work-board__header-meta {
  display: flex;
  flex: 1 1 0;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.my-work-board__title {
  font-size: inherit;
  font-weight: inherit;
  white-space: nowrap;
}

.my-work-board__header-notice {
  min-width: 0;
  color: rgba(15, 23, 42, 0.55);
  font-size: 12px;
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.my-work-board__tabs {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0;
  padding: 4px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.my-work-board__tab-button {
  position: relative;
  z-index: 1;
  border: none;
  background: transparent;
  color: rgba(15, 23, 42, 0.62);
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transform: translateY(0);
  transition: background-color 0.22s ease, color 0.22s ease, box-shadow 0.22s ease, transform 0.22s ease;
}

.my-work-board__tab-button:hover {
  color: rgba(15, 23, 42, 0.88);
}

.my-work-board__tab-button[data-active='true'] {
  background: rgba(255, 255, 255, 0.92);
  color: rgba(15, 23, 42, 0.92);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
  transform: translateY(-1px);
}

.my-work-board__tab-button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.18), 0 1px 3px rgba(15, 23, 42, 0.12);
}

.my-work-board__panel {
  height: clamp(340px, 45vh, 430px);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.my-work-board__panel--mobile {
  height: auto;
  overflow: visible;
}

.my-work-board__empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.my-work-board__columns-scrollbar {
  flex: 1;
  min-height: 0;
}

.my-work-board__columns-scrollbar--mobile {
  flex: none;
  height: auto;
}

.my-work-board__columns {
  display: grid;
  grid-template-columns: repeat(var(--my-work-board-column-count), minmax(220px, 1fr));
  gap: 12px;
  align-items: stretch;
}

.my-work-board__columns--mobile {
  grid-template-columns: 1fr;
  min-width: 100% !important;
}

.my-work-board__column {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 12px 0 12px 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 220px;
  box-sizing: border-box;
}

.my-work-board__column--board {
  background: #fff;
}

.my-work-board__column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 600;
  padding-right: 12px;
}

.my-work-board__column-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.my-work-board__column-icon {
  color: rgba(15, 23, 42, 0.55);
  flex-shrink: 0;
}

.my-work-board__columns--mobile .my-work-board__column {
  height: clamp(220px, 42vh, 320px);
  min-width: 0;
}

.my-work-board__column-body-scrollbar {
  flex: 1;
  min-height: 0;
}

.my-work-board__column-body-scrollbar :deep(.n-scrollbar-rail.n-scrollbar-rail--vertical) {
  right: 1px;
}

.my-work-board__column-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.my-work-board__card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  width: 100%;
  text-align: left;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: #fff;
  padding: 12px;
  cursor: pointer;
}

.my-work-board__card:hover {
  border-color: rgba(24, 160, 88, 0.28);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
}

.my-work-board__card-title {
  font-weight: 600;
  color: var(--n-text-color);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.my-work-board__card-subtitle,
.my-work-board__card-meta,
.my-work-board__column-empty,
.my-work-board__empty {
  color: rgba(15, 23, 42, 0.6);
  font-size: 12px;
}

.my-work-board__card-subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
}

.my-work-board__column-view-more {
  padding: 8px 0 4px;
  text-align: center;
}

.my-work-board__card-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.25);
  white-space: nowrap;
  line-height: 1.4;
}

@media (max-width: 768px) {
  .my-work-board__header {
    flex-direction: column;
    align-items: stretch;
  }

  .my-work-board__tabs {
    width: fit-content;
    max-width: 100%;
  }
}
</style>
