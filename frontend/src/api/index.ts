import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (
      error?.response?.status === 401 &&
      typeof window !== 'undefined' &&
      !window.location.pathname.startsWith('/login')
    ) {
      const next = `${window.location.pathname}${window.location.search}`
      window.location.assign(`/login?next=${encodeURIComponent(next)}`)
    }
    return Promise.reject(error)
  }
)

// Task types
export interface Task {
  id: number
  project_id: number
  project_name?: string | null
  project_path_with_namespace?: string | null
  project_url?: string | null
  issue_iid: number | null
  issue_url?: string | null
  issue_id: number | null
  note_id: number | null
  user_prompt: string
  branch_name: string | null
  branch_url?: string | null
  merge_request_iid: number | null
  merge_request_url: string | null
  status: string
  priority: number
  scheduled_at: string | null
  container_id: string | null
  target_branch: string
  target_branch_url?: string | null
  commit_sha: string | null
  error_message: string | null
  additions: number
  deletions: number
  total_changes: number
  is_manual: boolean
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
}

// Project and Branch types for manual task creation
export interface Project {
  id: number
  name: string
  path_with_namespace: string
}

export interface Branch {
  name: string
}

// Request types
export interface CreateTaskRequest {
  project_id?: number | null
  branch_name: string
  target_branch: string
  user_prompt: string
  priority?: number
  delay_seconds?: number
  scheduled_datetime?: string
}

export interface TaskLog {
  id: number
  task_id: number
  log_level: string
  message: string
  created_at: string
}

export interface TaskStats {
  additions: number
  deletions: number
  total: number
}

export interface Container {
  id: string
  name: string
  status: string
  task_id: number | null
  project_id: number | null
  issue_iid: number | null
  created_at: string
}

export interface Stats {
  total: number
  pending: number
  queued: number
  running: number
  completed: number
  failed: number
  cancelled: number
}

export interface RuntimeConfig {
  max_concurrency: number
  task_timeout: number
  scheduler_interval: number
  default_target_branch: string
}

export interface AuthConfig {
  oidc_enabled: boolean
  oidc_issuer_url: string
  oidc_client_id: string
  oidc_redirect_uri: string
  session_cookie_name: string
  session_ttl_seconds: number
  cookie_secure: boolean
  cookie_samesite: string
  auth_admin_usernames: string
  auth_admin_gitlab_groups: string
  oidc_client_secret_configured: boolean
}

export interface Config {
  runtime: RuntimeConfig
  auth: AuthConfig
}

export interface RuntimeConfigUpdate extends Partial<RuntimeConfig> {}

export interface AuthConfigUpdate extends Partial<Omit<AuthConfig, 'oidc_client_secret_configured'>> {
  oidc_client_secret?: string
  clear_oidc_client_secret?: boolean
}

export interface ConfigUpdate {
  runtime?: RuntimeConfigUpdate
  auth?: AuthConfigUpdate
}

export interface OidcConfigTestResult {
  issuer: string
  authorization_endpoint: string
  token_endpoint: string
  userinfo_endpoint: string
  authorization_url_preview: string
}

export interface AuthUser {
  id: number
  gitlab_user_id: number
  username: string
  display_name: string | null
  email: string | null
  avatar_url: string | null
  platform_role: string
}

export interface AuthStatus {
  oidc_enabled: boolean
  authenticated: boolean
  user: AuthUser | null
}

// API functions
export async function getTasks(params?: { status?: string; project_id?: number }): Promise<Task[]> {
  const response = await api.get('/tasks', { params })
  return response.data
}

export async function getTask(id: number): Promise<Task> {
  const response = await api.get(`/tasks/${id}`)
  return response.data
}

export async function getTaskLogs(id: number): Promise<TaskLog[]> {
  const response = await api.get(`/tasks/${id}/logs`)
  return response.data
}

export async function getTaskContainerLogs(id: number): Promise<{
  container_id: string | null
  container_status: string
  logs: string
  status: string
}> {
  const response = await api.get(`/tasks/${id}/container-logs`)
  return response.data
}

export async function getTaskStats(id: number): Promise<TaskStats> {
  const response = await api.get(`/tasks/${id}/stats`)
  return response.data
}

export async function cancelTask(id: number): Promise<void> {
  await api.post(`/tasks/${id}/cancel`)
}

export async function retryTask(id: number): Promise<void> {
  await api.post(`/tasks/${id}/retry`)
}

export async function executeTask(id: number): Promise<void> {
  await api.post(`/tasks/${id}/execute`)
}

export async function getContainers(): Promise<Container[]> {
  const response = await api.get('/containers')
  return response.data
}

export async function getContainerLogs(containerId: string): Promise<string> {
  const response = await api.get(`/containers/${containerId}/logs`)
  return response.data
}

export async function getStats(): Promise<Stats> {
  const response = await api.get('/stats')
  return response.data
}

export async function getConfig(): Promise<Config> {
  const response = await api.get('/config')
  return response.data
}

export async function updateConfig(config: ConfigUpdate): Promise<Config> {
  const response = await api.patch('/config', config)
  return response.data
}

export async function resetConfig(): Promise<Config> {
  const response = await api.post('/config/reset')
  return response.data
}

export async function resetConfigKey(key: string): Promise<Config> {
  const response = await api.delete(`/config/${key}`)
  return response.data
}

export async function testOidcConfig(auth: AuthConfigUpdate): Promise<OidcConfigTestResult> {
  const response = await api.post('/config/oidc/test', { auth })
  return response.data
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await api.get('/auth/me')
  return response.data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}

// Manual task creation APIs
export async function getProjects(): Promise<Project[]> {
  const response = await api.get('/projects')
  return response.data
}

export async function getBranches(projectId: number): Promise<Branch[]> {
  const response = await api.get(`/projects/${projectId}/branches`)
  return response.data
}

export async function createTask(request: CreateTaskRequest): Promise<Task> {
  const response = await api.post('/tasks', request)
  return response.data
}

export default api
