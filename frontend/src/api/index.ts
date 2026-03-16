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
      const detail =
        typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : ''
      const reason = detail ? `&reason=${encodeURIComponent(detail)}` : ''
      window.location.assign(`/login?next=${encodeURIComponent(next)}${reason}`)
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
  initiator_user_id?: number | null
  initiator_gitlab_user_id?: number | null
  initiator_username?: string | null
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
  input_tokens: number | null
  output_tokens: number | null
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
  default_branch?: string
}

export interface Branch {
  name: string
}

// Request types
export interface CreateTaskRequest {
  project_id?: number | null
  branch_name: string
  base_branch?: string
  target_branch: string
  user_prompt: string
  priority?: number
  delay_seconds?: number
  scheduled_datetime?: string
}

export interface RescheduleTaskRequest {
  scheduled_datetime: string
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

export interface AnalyticsSummary {
  total_tasks: number
  total_additions: number
  total_deletions: number
  total_changes: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
  finished_tasks: number
  success_rate: number | null
  failure_rate: number | null
  tracked_initiator_tasks: number
  token_tracked_tasks: number
  initiator_tracking_started_at: string | null
  avg_execution_seconds: number | null
  max_execution_seconds: number | null
  avg_queue_wait_seconds: number | null
  max_queue_wait_seconds: number | null
  avg_total_tokens_per_tracked_task: number | null
  max_total_tokens_per_tracked_task: number | null
}

export interface AnalyticsProjectRow {
  project_id: number
  project_name: string
  project_path_with_namespace: string | null
  task_count: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
  success_rate: number | null
  additions: number
  deletions: number
  total_changes: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  avg_execution_seconds: number | null
  avg_queue_wait_seconds: number | null
  last_task_at: string | null
}

export interface AnalyticsInitiatorRow {
  initiator_username: string
  initiator_gitlab_user_id: number | null
  task_count: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
  success_rate: number | null
  additions: number
  deletions: number
  total_changes: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  avg_execution_seconds: number | null
  avg_queue_wait_seconds: number | null
  last_task_at: string | null
}

export interface AnalyticsTrendPoint {
  date: string
  task_count: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
  additions: number
  deletions: number
  total_changes: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  avg_execution_seconds: number | null
}

export interface AnalyticsPriorityWaitRow {
  priority: number
  task_count: number
  avg_queue_wait_seconds: number | null
  max_queue_wait_seconds: number | null
}

export interface AnalyticsErrorRow {
  category: string
  count: number
  share_of_failed: number
  sample_message: string | null
}

export interface AnalyticsResponse {
  window_days: number
  generated_at: string
  summary: AnalyticsSummary
  projects: AnalyticsProjectRow[]
  initiators: AnalyticsInitiatorRow[]
  trends: AnalyticsTrendPoint[]
  priority_waits: AnalyticsPriorityWaitRow[]
  error_breakdown: AnalyticsErrorRow[]
}

export interface PagePermissions {
  monitor: boolean
  schedule_overview: boolean
  analytics: boolean
  oidc_diagnostics: boolean
}

export interface RuntimeConfig {
  max_concurrency: number
  task_timeout: number
  scheduler_interval: number
  default_target_branch: string
  max_retries: number
  retry_delay: number
  alert_on_failure: boolean
  alert_webhook_url_configured: boolean
  anthropic_base_url: string
  anthropic_api_key_configured: boolean
  anthropic_model: string
  claude_max_turns: number
  allow_monitor_for_users: boolean
  allow_schedule_overview_for_users: boolean
  allow_analytics_for_users: boolean
  allow_oidc_diagnostics_for_users: boolean
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

export interface IntegrationConfig {
  gitlab_url: string
  gitlab_bot_token_configured: boolean
  gitlab_admin_token_configured: boolean
  gitlab_webhook_secret_configured: boolean
}

export interface Config {
  runtime: RuntimeConfig
  auth: AuthConfig
  integration: IntegrationConfig
}

export interface RuntimeConfigUpdate
  extends Partial<Omit<RuntimeConfig, 'alert_webhook_url_configured' | 'anthropic_api_key_configured'>> {
  alert_webhook_url?: string
  clear_alert_webhook_url?: boolean
  anthropic_api_key?: string
  clear_anthropic_api_key?: boolean
}

export interface AuthConfigUpdate extends Partial<Omit<AuthConfig, 'oidc_client_secret_configured'>> {
  oidc_client_secret?: string
  clear_oidc_client_secret?: boolean
}

export interface IntegrationConfigUpdate
  extends Partial<
    Omit<
      IntegrationConfig,
      'gitlab_bot_token_configured' | 'gitlab_admin_token_configured' | 'gitlab_webhook_secret_configured'
    >
  > {
  gitlab_bot_token?: string
  clear_gitlab_bot_token?: boolean
  gitlab_admin_token?: string
  clear_gitlab_admin_token?: boolean
  gitlab_webhook_secret?: string
  clear_gitlab_webhook_secret?: boolean
}

export interface ConfigUpdate {
  runtime?: RuntimeConfigUpdate
  auth?: AuthConfigUpdate
  integration?: IntegrationConfigUpdate
}

export interface OidcConfigTestResult {
  issuer: string
  authorization_endpoint: string
  token_endpoint: string
  userinfo_endpoint: string
  authorization_url_preview: string
  required_scopes: string[]
  warnings: string[]
}

export interface GitLabConfigTestResult {
  server_version: string
  username: string
  gitlab_url: string
}

export interface GitLabProjectWebhookSetupResult {
  action: 'created' | 'updated' | string
  project_id: number
  project_name: string
  project_path_with_namespace: string
  webhook_url: string
  hook_id: number
}

export interface GitLabProjectWebhookStatusResult {
  project_id: number
  project_name: string
  project_path_with_namespace: string
  target_webhook_url: string
  status: 'configured' | 'missing' | 'needs_attention' | 'error' | string
  status_detail: string | null
  hook_found: boolean
  hook_id: number | null
  hook_url: string | null
  note_events: boolean | null
  enable_ssl_verification: boolean | null
  managed_secret_configured: boolean
  global_secret_fallback_configured: boolean
  secret_mode: 'project' | 'global_fallback' | 'none' | string
}

export interface OidcDiagnosticsCheck {
  key: string
  label: string
  status: string
  detail: string
}

export interface OidcDiagnosticsResult {
  oidc_enabled: boolean
  break_glass_enabled: boolean
  issuer_url: string
  redirect_uri: string
  client_id_configured: boolean
  client_secret_configured: boolean
  session_cookie_name: string
  session_ttl_seconds: number
  cookie_secure: boolean
  cookie_samesite: string
  required_scopes: string[]
  required_scope_string: string
  authorization_url_preview: string | null
  discovery_issuer: string | null
  authorization_endpoint: string | null
  token_endpoint: string | null
  userinfo_endpoint: string | null
  checks: OidcDiagnosticsCheck[]
  warnings: string[]
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
  break_glass_enabled?: boolean
  break_glass_username?: string | null
  authenticated: boolean
  page_permissions: PagePermissions
  user: AuthUser | null
}

export interface AdminUser {
  id: number
  gitlab_user_id: number
  username: string
  display_name: string | null
  email: string | null
  avatar_url: string | null
  platform_role: string
  platform_role_source: string
  state: string
  last_login_at: string | null
  created_at: string
  active_session_count: number
  last_session_seen_at: string | null
  is_current_user: boolean
}

export interface AdminUserUpdateRequest {
  platform_role?: string
  state?: string
}

export interface RevokeUserSessionsResponse {
  status: string
  revoked_count: number
}

export interface BreakGlassLoginRequest {
  username: string
  password: string
  next?: string
}

export interface BreakGlassLoginResponse {
  status: string
  next_path: string
}

export interface SessionInfo {
  id: string
  created_at: string
  last_seen_at: string | null
  expires_at: string
  revoked_at: string | null
  ip_address: string | null
  user_agent: string | null
  status: string
  current: boolean
  has_gitlab_access_token: boolean
  has_gitlab_refresh_token: boolean
}

export interface RevokeSessionResponse {
  status: string
  session_id: string
  current_session_revoked: boolean
}

// API functions
export async function getTasks(params?: {
  status?: string
  project_id?: number
  initiator_username?: string
}): Promise<Task[]> {
  const response = await api.get('/tasks', { params })
  return response.data
}

export async function getScheduledTasks(params?: { project_id?: number }): Promise<Task[]> {
  const response = await api.get('/tasks/scheduled', { params })
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

export async function retryTask(id: number, scheduledDatetime?: string): Promise<void> {
  const body = scheduledDatetime ? { scheduled_datetime: scheduledDatetime } : undefined
  await api.post(`/tasks/${id}/retry`, body)
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

export async function getAnalytics(days: number): Promise<AnalyticsResponse> {
  const response = await api.get('/stats/analytics', { params: { days } })
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

export async function testGitLabConfig(
  integration: IntegrationConfigUpdate,
): Promise<GitLabConfigTestResult> {
  const response = await api.post('/config/gitlab/test', { integration })
  return response.data
}

export async function setupGitLabProjectWebhook(
  projectId: number,
): Promise<GitLabProjectWebhookSetupResult> {
  const response = await api.post(`/config/gitlab/projects/${projectId}/webhook`)
  return response.data
}

export async function getGitLabProjectWebhookStatus(
  projectId: number,
): Promise<GitLabProjectWebhookStatusResult> {
  const response = await api.get(`/config/gitlab/projects/${projectId}/webhook`)
  return response.data
}

export async function listGitLabProjectWebhookStatuses(): Promise<GitLabProjectWebhookStatusResult[]> {
  const response = await api.get('/config/gitlab/webhooks')
  return response.data
}

export async function getOidcDiagnostics(): Promise<OidcDiagnosticsResult> {
  const response = await api.get('/config/oidc/diagnostics')
  return response.data
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await api.get('/auth/me')
  return response.data
}

export async function breakGlassLogin(payload: BreakGlassLoginRequest): Promise<BreakGlassLoginResponse> {
  const response = await api.post('/auth/break-glass/login', payload)
  return response.data
}

export async function getSessions(): Promise<SessionInfo[]> {
  const response = await api.get('/auth/sessions')
  return response.data
}

export async function revokeSession(sessionId: string): Promise<RevokeSessionResponse> {
  const response = await api.post(`/auth/sessions/${sessionId}/revoke`)
  return response.data
}

export async function getAdminUsers(): Promise<AdminUser[]> {
  const response = await api.get('/admin/users')
  return response.data
}

export async function updateAdminUser(
  userId: number,
  payload: AdminUserUpdateRequest
): Promise<AdminUser> {
  const response = await api.patch(`/admin/users/${userId}`, payload)
  return response.data
}

export async function revokeAdminUserSessions(userId: number): Promise<RevokeUserSessionsResponse> {
  const response = await api.post(`/admin/users/${userId}/sessions/revoke`)
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

export async function rescheduleTask(taskId: number, request: RescheduleTaskRequest): Promise<Task> {
  const response = await api.patch(`/tasks/${taskId}/schedule`, request)
  return response.data
}

export default api
