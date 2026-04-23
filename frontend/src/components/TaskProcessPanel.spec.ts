import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import type { Task } from '../api'
import TaskProcessPanel from './TaskProcessPanel.vue'
import taskProcessPanelSource from './TaskProcessPanel.vue?raw'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

const NCardStub = {
  name: 'NCard',
  inheritAttrs: false,
  setup(_props: unknown, { attrs, slots }: { attrs: Record<string, unknown>; slots: Record<string, () => unknown> }) {
    return () => h('section', { class: attrs.class, style: attrs.style }, [
      h('header', { class: 'n-card__header' }, slots.header?.()),
      h('div', { class: 'n-card__content' }, slots.default?.()),
    ])
  },
}

const passthroughStub = (name: string, tag = 'div') => ({
  name,
  setup(_props: unknown, { slots }: { slots: Record<string, () => unknown> }) {
    return () => h(tag, { class: name }, slots.default?.())
  },
})

function createTask(status: Task['status']): Task {
  return {
    id: 1,
    issue_id: null,
    project_id: 1,
    user_prompt: 'Prompt',
    status,
    priority: 0,
    is_retry: false,
    retry_source_task_id: null,
    scheduled_at: null,
    container_id: null,
    container_name: null,
    commit_sha: null,
    error_message: null,
    additions: 0,
    deletions: 0,
    total_changes: 0,
    input_tokens: null,
    output_tokens: null,
    provider_id: null,
    created_at: '2026-04-23T10:00:00Z',
    updated_at: '2026-04-23T10:00:00Z',
    started_at: null,
    completed_at: null,
  }
}

function mountComponent(status: Task['status']) {
  return mount(TaskProcessPanel, {
    props: {
      task: createTask(status),
      taskLogs: [],
      isActive: status === 'running' || status === 'queued' || status === 'pending',
      terminalHtml: '',
      taskStatus: status,
    },
    global: {
      stubs: {
        NCard: NCardStub,
        NTag: passthroughStub('NTag', 'span'),
        NIcon: passthroughStub('NIcon', 'i'),
        NTabs: passthroughStub('NTabs'),
        NTabPane: passthroughStub('NTabPane'),
        NEmpty: passthroughStub('NEmpty'),
        NCollapse: passthroughStub('NCollapse'),
        NCollapseItem: passthroughStub('NCollapseItem'),
        NButton: passthroughStub('NButton', 'button'),
      },
    },
  })
}

describe('TaskProcessPanel', () => {
  it('adds the running glow class to the card when the task is running', () => {
    const wrapper = mountComponent('running')

    expect(wrapper.get('.task-process-panel').classes()).toContain('task-process-panel--running')
  })

  it('keeps the running background glow subtle', () => {
    expect(taskProcessPanelSource).toContain('rgba(74, 222, 128, 0.07)')
  })
})
