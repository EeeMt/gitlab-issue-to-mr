<template>
  <n-card class="my-work-board" :bordered="false" data-testid="dashboard-my-work-board">
    <template #header>
      <div class="my-work-board__header">
        <span>{{ t('dashboard.myWorkBoard.title') }}</span>
      </div>
    </template>

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

    <div
      v-if="hasMoreItems"
      class="my-work-board__notice"
      :data-testid="`my-work-board-notice-${activeTab}`"
    >
      {{ t('dashboard.myWorkBoard.limitNotice', { shown: visibleLimit, total: activeTotal }) }}
    </div>

    <div
      v-if="activeColumns.every((column) => column.count === 0)"
      :data-testid="`my-work-board-empty-${activeTab}`"
      class="my-work-board__empty"
    >
      {{ t('dashboard.myWorkBoard.emptyBoard') }}
    </div>

    <div class="my-work-board__columns" :class="{ 'my-work-board__columns--mobile': isMobile }">
      <section
        v-for="column in activeColumns"
        :key="`${activeTab}-${column.status}`"
        class="my-work-board__column"
        :data-testid="`${activeTab === 'issues' ? 'issue' : 'task'}-column-${column.status}`"
      >
        <header class="my-work-board__column-header">
          <span>{{ column.label }}</span>
          <span>{{ column.count }}</span>
        </header>

        <div class="my-work-board__column-body">
          <button
            v-for="item in column.items"
            :key="item.id"
            type="button"
            class="my-work-board__card"
            :data-testid="`${activeTab === 'issues' ? 'issue' : 'task'}-card-${item.id}`"
            :title="item.fullTitle || item.title"
            @click="emit('select', item.route)"
          >
            <div class="my-work-board__card-title">{{ item.title }}</div>
            <div class="my-work-board__card-subtitle">{{ item.subtitle }}</div>
            <div class="my-work-board__card-meta">{{ item.meta.join(' · ') }}</div>
          </button>

          <div v-if="column.items.length === 0" class="my-work-board__column-empty">
            {{ t('dashboard.myWorkBoard.emptyColumn') }}
          </div>
        </div>
      </section>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NCard } from 'naive-ui'
import { useI18n } from 'vue-i18n'

export type BoardKind = 'issues' | 'tasks'

export interface BoardCardItem {
  id: number
  title: string
  fullTitle?: string
  subtitle: string
  meta: string[]
  route: string
}

export interface BoardColumn {
  status: string
  label: string
  count: number
  items: BoardCardItem[]
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
}>()

const { t } = useI18n()
const activeTab = ref<BoardKind>('issues')

const activeColumns = computed(() =>
  activeTab.value === 'issues' ? props.issueColumns : props.taskColumns,
)

const activeTotal = computed(() =>
  activeTab.value === 'issues' ? props.issueTotal : props.taskTotal,
)

const hasMoreItems = computed(() => activeTotal.value > props.visibleLimit)
</script>

<style scoped>
.my-work-board {
  border-radius: var(--app-card-radius);
}

.my-work-board__tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.my-work-board__tab-button {
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  border-radius: 999px;
  padding: 6px 12px;
  cursor: pointer;
}

.my-work-board__tab-button[data-active='true'] {
  background: rgba(24, 160, 88, 0.08);
  border-color: rgba(24, 160, 88, 0.32);
  color: #18a058;
}

.my-work-board__columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.my-work-board__columns--mobile {
  grid-template-columns: 1fr;
}

.my-work-board__column {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 12px;
  background: rgba(248, 250, 252, 0.8);
}

.my-work-board__column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 600;
}

.my-work-board__column-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 440px;
  overflow-y: auto;
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

.my-work-board__notice,
.my-work-board__card-subtitle,
.my-work-board__card-meta,
.my-work-board__column-empty,
.my-work-board__empty {
  color: rgba(15, 23, 42, 0.6);
  font-size: 12px;
}
</style>
