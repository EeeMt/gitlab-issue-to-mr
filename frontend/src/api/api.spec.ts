import { describe, it, expect, vi, beforeEach } from 'vitest'

// Create mock functions and handlers using hoisted to ensure they're available when vi.mock runs
const { mockAxiosGet, mockAxiosPost, mockAxiosPatch, mockAxiosDelete } = vi.hoisted(() => {
  let successHandler: ((response: any) => any) | null = null
  let errorHandler: ((error: any) => any) | null = null

  return {
    mockAxiosGet: vi.fn(),
    mockAxiosPost: vi.fn(),
    mockAxiosPatch: vi.fn(),
    mockAxiosDelete: vi.fn(),
    successHandler,
    errorHandler
  }
})

// Mock the axios module before importing the api
vi.mock('axios', () => {
  const mockInstance = {
    get: mockAxiosGet,
    post: mockAxiosPost,
    patch: mockAxiosPatch,
    delete: mockAxiosDelete,
    interceptors: {
      response: {
        use: vi.fn((success, error) => {
          // Store handlers for testing
          ;(mockInstance as any)._successHandler = success
          ;(mockInstance as any)._errorHandler = error
        })
      }
    }
  }

  // axios.create returns the same instance (mockInstance)
  const createFn = () => mockInstance

  return {
    default: Object.assign(createFn, { create: createFn }),
    _getErrorHandler: () => (mockInstance as any)._errorHandler
  }
})

// Import after mocking
import {
  getTasks,
  getTask,
  createTask,
  cancelTask,
  retryTask,
  executeTask,
  getStats,
  getProjects,
  getProjectCIAutoRepairAvailability,
  getBranches,
  getAuthStatus,
  downloadTaskArchive,
  downloadSkill,
  cleanupSystemData,
  verifyWorkerProfileRuntime
} from './index'
import * as apiModule from './index'

describe('API functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('getTasks', () => {
    it('should call /api/tasks with params', async () => {
      const mockTasks = [
        {
          id: 1,
          project_id: 1,
          project_name: 'Test Project',
          issue_iid: 10,
          user_prompt: 'Test prompt',
          status: 'PENDING',
          priority: 0,
          branch_name: 'feature/test',
          target_branch: 'main',
          is_manual: false,
          created_at: '2026-03-01T00:00:00Z',
          updated_at: '2026-03-01T00:00:00Z'
        }
      ]
      mockAxiosGet.mockResolvedValue({ data: mockTasks })

      const result = await getTasks({ status: 'PENDING' })

      expect(result).toEqual(mockTasks)
      expect(mockAxiosGet).toHaveBeenCalledWith('/tasks', { params: { status: 'PENDING' } })
    })

    it('should call /api/tasks with project_id and initiator_username params', async () => {
      const mockTasks: any[] = []
      mockAxiosGet.mockResolvedValue({ data: mockTasks })

      await getTasks({ project_id: 123, initiator_username: 'testuser' })

      expect(mockAxiosGet).toHaveBeenCalledWith('/tasks', {
        params: { project_id: 123, initiator_username: 'testuser' }
      })
    })

    it('should handle errors gracefully', async () => {
      const error = { response: { status: 500, data: { detail: 'Internal server error' } } }
      mockAxiosGet.mockRejectedValue(error)

      await expect(getTasks()).rejects.toEqual(error)
    })

    it('should return empty array when no tasks', async () => {
      mockAxiosGet.mockResolvedValue({ data: [] })

      const result = await getTasks()

      expect(result).toEqual([])
    })
  })

  describe('getTask', () => {
    it('should call /api/tasks/:id', async () => {
      const mockTask = {
        id: 42,
        project_id: 1,
        issue_iid: 10,
        user_prompt: 'Test prompt',
        status: 'RUNNING',
        priority: 1,
        branch_name: 'feature/test',
        target_branch: 'main',
        is_manual: false,
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z'
      }
      mockAxiosGet.mockResolvedValue({ data: mockTask })

      const result = await getTask(42)

      expect(result).toEqual(mockTask)
      expect(mockAxiosGet).toHaveBeenCalledWith('/tasks/42')
    })

    it('should handle 404 error', async () => {
      const error = { response: { status: 404, data: { detail: 'Task not found' } } }
      mockAxiosGet.mockRejectedValue(error)

      await expect(getTask(999)).rejects.toEqual(error)
    })
  })

  describe('downloadTaskArchive', () => {
    it('downloads the task runtime archive as a blob', async () => {
      const blob = new Blob(['archive'])
      mockAxiosGet.mockResolvedValue({ data: blob })

      const result = await downloadTaskArchive(42)

      expect(result).toBe(blob)
      expect(mockAxiosGet).toHaveBeenCalledWith('/tasks/42/archive/download', { responseType: 'blob' })
    })
  })

  describe('downloadSkill', () => {
    it('downloads the current skill package as a blob', async () => {
      const blob = new Blob(['skill package'])
      mockAxiosGet.mockResolvedValue({ data: blob })

      const result = await downloadSkill(4)

      expect(result).toBe(blob)
      expect(mockAxiosGet).toHaveBeenCalledWith('/skills/4/download', { responseType: 'blob' })
    })
  })

  describe('cleanupSystemData', () => {
    it('posts cleanup options to the maintenance endpoint', async () => {
      const response = {
        deleted_issues: 1,
        deleted_tasks: 2,
        skipped_active_issues: 0,
        skipped_active_tasks: 0,
        deleted_archives: 2,
        missing_archives: 0,
        deleted_workspaces: 1,
        container_cleanup_errors: [],
        file_cleanup_errors: []
      }
      mockAxiosPost.mockResolvedValue({ data: response })

      const result = await cleanupSystemData({ older_than_days: 30, force: true })

      expect(result).toEqual(response)
      expect(mockAxiosPost).toHaveBeenCalledWith('/config/maintenance/cleanup-system-data', {
        older_than_days: 30,
        force: true
      })
    })
  })

  describe('createTask', () => {
    it('should POST to /api/tasks with request body', async () => {
      const request = {
        project_id: 1,
        branch_name: 'feature/new-feature',
        target_branch: 'main',
        user_prompt: 'Create a new feature',
        priority: 1
      }
      const mockResponse = {
        id: 100,
        ...request,
        status: 'PENDING',
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z'
      }
      mockAxiosPost.mockResolvedValue({ data: mockResponse })

      const result = await createTask(request)

      expect(result).toEqual(mockResponse)
      expect(mockAxiosPost).toHaveBeenCalledWith('/tasks', request)
    })

    it('should return created task', async () => {
      const request = {
        branch_name: 'feature/test',
        target_branch: 'develop',
        user_prompt: 'Test task'
      }
      const mockResponse = {
        id: 101,
        project_id: null,
        ...request,
        status: 'PENDING',
        is_manual: true,
        created_at: '2026-03-01T00:00:00Z',
        updated_at: '2026-03-01T00:00:00Z'
      }
      mockAxiosPost.mockResolvedValue({ data: mockResponse })

      const result = await createTask(request)

      expect(result.id).toBe(101)
      expect(result.status).toBe('PENDING')
    })

    it('should handle validation errors', async () => {
      const error = { response: { status: 422, data: { detail: 'Validation error: user_prompt is required' } } }
      mockAxiosPost.mockRejectedValue(error)

      await expect(createTask({
        branch_name: 'feature/test',
        target_branch: 'main',
        user_prompt: ''
      })).rejects.toEqual(error)
    })
  })

  describe('verifyWorkerProfileRuntime', () => {
    it('allows the long-running verification endpoint to return its result', async () => {
      const response = { verified_at: '2026-09-02T04:30:03Z' }
      mockAxiosPost.mockResolvedValue({ data: response })

      const result = await verifyWorkerProfileRuntime(4)

      expect(result).toEqual(response)
      expect(mockAxiosPost).toHaveBeenCalledWith(
        '/worker-profiles/4/verify-runtime',
        {},
        { timeout: 240000 }
      )
    })
  })

  describe('cancelTask', () => {
    it('should POST to /api/tasks/:id/cancel', async () => {
      mockAxiosPost.mockResolvedValue({ data: undefined })

      await cancelTask(5)

      expect(mockAxiosPost).toHaveBeenCalledWith('/tasks/5/cancel')
    })
  })

  describe('retryTask', () => {
    it('should POST to /api/tasks/:id/retry with scheduled_datetime', async () => {
      mockAxiosPost.mockResolvedValue({ data: undefined })

      await retryTask(10, '2026-04-01T00:00:00Z')

      expect(mockAxiosPost).toHaveBeenCalledWith('/tasks/10/retry', { scheduled_datetime: '2026-04-01T00:00:00Z' })
    })

    it('should POST to /api/tasks/:id/retry without body when no scheduledDatetime', async () => {
      mockAxiosPost.mockResolvedValue({ data: undefined })

      await retryTask(10)

      expect(mockAxiosPost).toHaveBeenCalledWith('/tasks/10/retry', undefined)
    })
  })

  describe('executeTask', () => {
    it('should POST to /api/tasks/:id/execute', async () => {
      mockAxiosPost.mockResolvedValue({ data: undefined })

      await executeTask(7)

      expect(mockAxiosPost).toHaveBeenCalledWith('/tasks/7/execute')
    })
  })

  describe('getStats', () => {
    it('should call /api/stats', async () => {
      const mockStats = {
        total: 100,
        pending: 10,
        queued: 5,
        running: 3,
        completed: 80,
        failed: 2,
        cancelled: 0
      }
      mockAxiosGet.mockResolvedValue({ data: mockStats })

      const result = await getStats()

      expect(result).toEqual(mockStats)
      expect(mockAxiosGet).toHaveBeenCalledWith('/stats', { params: undefined })
    })
  })

  describe('getProjects', () => {
    it('should call /api/projects', async () => {
      const mockProjects = [
        { id: 1, name: 'Project A', path_with_namespace: 'group/project-a', default_branch: 'main' },
        { id: 2, name: 'Project B', path_with_namespace: 'group/project-b', default_branch: 'develop' }
      ]
      mockAxiosGet.mockResolvedValue({ data: mockProjects })

      const result = await getProjects()

      expect(result).toEqual(mockProjects)
      expect(mockAxiosGet).toHaveBeenCalledWith('/projects')
    })

    it('should request CI auto-repair availability for one project', async () => {
      const availability = {
        project_id: 42,
        webhook_status: 'configured',
        webhook_status_issues: [],
        ci_auto_repair_available: true,
      }
      mockAxiosGet.mockResolvedValue({ data: availability })

      const result = await getProjectCIAutoRepairAvailability(42)

      expect(result).toEqual(availability)
      expect(mockAxiosGet).toHaveBeenCalledWith(
        '/projects/42/ci-auto-repair-availability'
      )
    })
  })

  describe('getBranches', () => {
    it('should call /api/projects/:id/branches', async () => {
      const mockBranches = [
        { name: 'main' },
        { name: 'develop' },
        { name: 'feature/new' }
      ]
      mockAxiosGet.mockResolvedValue({ data: mockBranches })

      const result = await getBranches(1)

      expect(result).toEqual(mockBranches)
      expect(mockAxiosGet).toHaveBeenCalledWith('/projects/1/branches')
    })
  })

  describe('getAuthStatus', () => {
    it('should call /api/auth/me', async () => {
      const mockAuthStatus = {
        oidc_enabled: true,
        authenticated: true,
        page_permissions: {
          monitor: true,
          schedule_overview: true,
          analytics: false,
          oidc_diagnostics: false
        },
        user: {
          id: 1,
          gitlab_user_id: 100,
          username: 'testuser',
          display_name: 'Test User',
          email: 'test@example.com',
          avatar_url: null,
          platform_role: 'platform_admin'
        }
      }
      mockAxiosGet.mockResolvedValue({ data: mockAuthStatus })

      const result = await getAuthStatus()

      expect(result).toEqual(mockAuthStatus)
      expect(mockAxiosGet).toHaveBeenCalledWith('/auth/me')
    })
  })

  describe('auth error handling', () => {
    it('should redirect to login on 401', async () => {
      const assignMock = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { pathname: '/tasks', search: '', assign: assignMock },
        writable: true,
        configurable: true
      })

      const error = {
        response: { status: 401, data: { detail: 'Unauthorized' } },
        config: { headers: {} }
      }

      // Get the error handler from the mock
      const axios = await import('axios')
      const handler = (axios as any)._getErrorHandler()

      // Simulate axios calling the error handler with the error
      // The handler returns Promise.reject(error) after redirecting, so we catch it
      if (handler) {
        handler(error).catch(() => {})
      }

      await new Promise(resolve => setTimeout(resolve, 0))

      expect(assignMock).toHaveBeenCalledWith(
        expect.stringContaining('/login')
      )
    })

    it('should skip redirect with X-Skip-Auth-Redirect header', async () => {
      const assignMock = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { pathname: '/some-path', search: '', assign: assignMock },
        writable: true,
        configurable: true
      })

      const error = {
        response: { status: 401, data: { detail: 'Unauthorized' } },
        config: { headers: { 'X-Skip-Auth-Redirect': 'true' } }
      }

      // Get the error handler from the mock
      const axios = await import('axios')
      const handler = (axios as any)._getErrorHandler()

      // Simulate axios calling the error handler with the error
      // The handler returns Promise.reject(error), so we catch it
      if (handler) {
        handler(error).catch(() => {})
      }

      await new Promise(resolve => setTimeout(resolve, 0))

      // With X-Skip-Auth-Redirect header, location.assign should NOT be called
      expect(assignMock).not.toHaveBeenCalled()
    })
  })

  describe('admin usage limits', () => {
    it('should call /api/admin/usage-limits/default', async () => {
      const getAdminUsageLimitDefault = (
        apiModule as unknown as Record<string, () => Promise<unknown>>
      ).getAdminUsageLimitDefault
      mockAxiosGet.mockResolvedValue({ data: { daily_tokens: { mode: 'custom', value: 1000 } } })

      expect(typeof getAdminUsageLimitDefault).toBe('function')
      await getAdminUsageLimitDefault?.()

      expect(mockAxiosGet).toHaveBeenCalledWith('/admin/usage-limits/default')
    })

    it('should call /api/admin/usage-limits/users', async () => {
      const listAdminUsageLimitUsers = (
        apiModule as unknown as Record<string, () => Promise<unknown>>
      ).listAdminUsageLimitUsers
      mockAxiosGet.mockResolvedValue({ data: [] })

      expect(typeof listAdminUsageLimitUsers).toBe('function')
      await listAdminUsageLimitUsers?.()

      expect(mockAxiosGet).toHaveBeenCalledWith('/admin/usage-limits/users')
    })

    it('should patch /api/admin/usage-limits/users/:id', async () => {
      const updateAdminUsageLimitUser = (
        apiModule as unknown as Record<string, (userId: number, payload: unknown) => Promise<unknown>>
      ).updateAdminUsageLimitUser
      const payload = {
        daily_tokens: { mode: 'inherit', value: null },
        weekly_tokens: { mode: 'custom', value: 4000 },
        daily_tasks: { mode: 'unlimited', value: null },
        weekly_tasks: { mode: 'inherit', value: null },
      }
      mockAxiosPatch.mockResolvedValue({ data: { user_id: 7 } })

      expect(typeof updateAdminUsageLimitUser).toBe('function')
      await updateAdminUsageLimitUser?.(7, payload)

      expect(mockAxiosPatch).toHaveBeenCalledWith('/admin/usage-limits/users/7', payload)
    })
  })

  describe('deleteIssueBranch', () => {
    it('should POST to /issues/123/delete-branch and return issue', async () => {
      const mockIssue = {
        id: 123,
        project_id: 1,
        issue_iid: 10,
        title: 'Test issue',
        delete_branch_on_close: true,
        branch_deleted: false
      }
      mockAxiosPost.mockResolvedValue({ data: mockIssue })

      const fn = (apiModule as unknown as Record<string, any>).deleteIssueBranch
      expect(typeof fn).toBe('function')

      const result = await fn(123)

      expect(mockAxiosPost).toHaveBeenCalledWith('/issues/123/delete-branch')
      expect(result).toEqual(mockIssue)
    })
  })

  describe('closeIssue', () => {
    it('should POST close choice to /issues/123/close and return issue', async () => {
      const mockIssue = {
        id: 123,
        project_id: 1,
        title: 'Test issue',
        status: 'closed',
        branch_deleted: true
      }
      mockAxiosPost.mockResolvedValue({ data: mockIssue })

      const fn = (apiModule as unknown as Record<string, any>).closeIssue
      expect(typeof fn).toBe('function')

      const result = await fn(123, { branch_action: 'delete', delete_branch: true })

      expect(mockAxiosPost).toHaveBeenCalledWith('/issues/123/close', {
        branch_action: 'delete',
        delete_branch: true,
      })
      expect(result).toEqual(mockIssue)
    })

    it('should keep branch when closeIssue is called without options', async () => {
      const mockIssue = {
        id: 123,
        project_id: 1,
        title: 'Test issue',
        status: 'closed',
        branch_deleted: false
      }
      mockAxiosPost.mockResolvedValue({ data: mockIssue })

      const fn = (apiModule as unknown as Record<string, any>).closeIssue
      const result = await fn(123)

      expect(mockAxiosPost).toHaveBeenCalledWith('/issues/123/close', {
        branch_action: 'keep',
        delete_branch: false,
      })
      expect(result).toEqual(mockIssue)
    })
  })
})
