import { vi } from 'vitest'
import type {
  Task,
  Project,
  Branch,
  PromptTemplate,
  Stats,
  Config,
  Container,
  TaskLog,
  TaskStats,
  MattermostNotificationConfig
} from '@/api'

// Mock data factories
export const createMockTask = (overrides = {}): Task => ({
  id: 1,
  project_id: 1,
  project_name: 'test-project',
  project_path_with_namespace: 'group/test-project',
  project_url: 'https://gitlab.example.com/group/test-project',
  issue_iid: 42,
  issue_url: 'https://gitlab.example.com/group/test-project/-/issues/42',
  issue_id: 100,
  note_id: null,
  user_prompt: 'Fix the login bug',
  initiator_user_id: 1,
  initiator_gitlab_user_id: 10,
  initiator_username: 'testuser',
  branch_name: 'fix-login-bug',
  branch_url: 'https://gitlab.example.com/group/test-project/-/tree/fix-login-bug',
  merge_request_iid: null,
  merge_request_url: null,
  status: 'pending',
  priority: 1,
  scheduled_at: null,
  container_id: null,
  target_branch: 'main',
  target_branch_url: null,
  commit_sha: null,
  error_message: null,
  additions: 0,
  deletions: 0,
  total_changes: 0,
  input_tokens: null,
  output_tokens: null,
  is_manual: true,
  created_at: '2026-03-31T10:00:00Z',
  updated_at: '2026-03-31T10:00:00Z',
  started_at: null,
  completed_at: null,
  ...overrides
})

export const createMockProject = (overrides = {}): Project => ({
  id: 1,
  name: 'test-project',
  path_with_namespace: 'group/test-project',
  default_branch: 'main',
  ...overrides
})

export const createMockBranch = (overrides = {}): Branch => ({
  name: 'main',
  ...overrides
})

export const createMockPromptTemplate = (overrides = {}): PromptTemplate => ({
  id: 1,
  name: 'Bug Fix Template',
  content: 'Fix the {{issue_type}} in {{file_path}}',
  variable_tips: { issue_type: 'Type of issue (bug, feature, etc.)', file_path: 'Path to the file' },
  is_active: true,
  created_at: '2026-03-31T10:00:00Z',
  updated_at: '2026-03-31T10:00:00Z',
  ...overrides
})

export const createMockStats = (overrides = {}): Stats => ({
  total: 10,
  pending: 2,
  queued: 3,
  running: 1,
  completed: 4,
  failed: 0,
  cancelled: 0,
  ...overrides
})

export const createMockContainer = (overrides = {}): Container => ({
  id: 'container-1',
  name: 'codify-1-p1-i42',
  status: 'running',
  task_id: 1,
  project_id: 1,
  issue_iid: 42,
  created_at: '2026-03-31T10:00:00Z',
  ...overrides
})

export const createMockTaskLog = (overrides = {}): TaskLog => ({
  id: 1,
  task_id: 1,
  log_level: 'info',
  message: 'Task started',
  created_at: '2026-03-31T10:00:00Z',
  ...overrides
})

export const createMockTaskStats = (overrides = {}): TaskStats => ({
  additions: 100,
  deletions: 50,
  total: 150,
  ...overrides
})

export const createMockMattermostNotificationConfig = (overrides = {}): MattermostNotificationConfig => ({
  integration: {
    mattermost_server_url: 'https://mattermost.example.com',
    mattermost_bot_token_configured: true
  },
  profiles: [],
  ...overrides
})

// Mock API functions
export const mockApi = {
  getTasks: vi.fn<() => Promise<Task[]>>(),
  getScheduledTasks: vi.fn<() => Promise<Task[]>>(),
  getTask: vi.fn<() => Promise<Task>>(),
  getTaskLogs: vi.fn<() => Promise<TaskLog[]>>(),
  getTaskContainerLogs: vi.fn<() => Promise<{ container_id: string | null; container_status: string; logs: string; status: string }>>(),
  getTaskStats: vi.fn<() => Promise<TaskStats>>(),
  cancelTask: vi.fn<() => Promise<void>>(),
  retryTask: vi.fn<() => Promise<void>>(),
  executeTask: vi.fn<() => Promise<void>>(),
  rescheduleTask: vi.fn<() => Promise<Task>>(),
  getContainers: vi.fn<() => Promise<Container[]>>(),
  getContainerLogs: vi.fn<() => Promise<string>>(),
  getStats: vi.fn<() => Promise<Stats>>(),
  getAnalytics: vi.fn<() => Promise<unknown>>(),
  getConfig: vi.fn<() => Promise<Config>>(),
  updateConfig: vi.fn<() => Promise<Config>>(),
  resetConfig: vi.fn<() => Promise<Config>>(),
  resetConfigKey: vi.fn<() => Promise<Config>>(),
  getProjects: vi.fn<() => Promise<Project[]>>(),
  getBranches: vi.fn<() => Promise<Branch[]>>(),
  createTask: vi.fn<() => Promise<Task>>(),
  getPromptTemplates: vi.fn<() => Promise<PromptTemplate[]>>(),
  createPromptTemplate: vi.fn<() => Promise<PromptTemplate>>(),
  updatePromptTemplate: vi.fn<() => Promise<PromptTemplate>>(),
  deletePromptTemplate: vi.fn<() => Promise<void>>(),
  getMattermostNotificationConfig: vi.fn<() => Promise<MattermostNotificationConfig>>(),
  updateMattermostIntegration: vi.fn<() => Promise<MattermostNotificationConfig>>(),
  getAuthStatus: vi.fn<() => Promise<unknown>>(),
  logout: vi.fn<() => Promise<void>>()
}

export const setupMockApi = () => {
  return mockApi
}

export const resetMockApi = () => {
  Object.values(mockApi).forEach(fn => {
    if (typeof fn.mock !== 'undefined') {
      fn.mockReset()
    }
  })
}
