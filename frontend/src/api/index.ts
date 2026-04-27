import axios from 'axios'

// Augment AxiosError so callers can access error.apiError with type safety
declare module 'axios' {
  interface AxiosError {
    apiError?: ApiError
  }
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Skip redirect if the request included X-Skip-Auth-Redirect header
    const skipRedirect = error?.config?.headers?.['X-Skip-Auth-Redirect'] === 'true'
    
    if (
      !skipRedirect &&
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

    // Normalize error for callers
    const apiError: ApiError = {
      status: error?.response?.status ?? 0,
      message: error?.message ?? 'Unknown error',
      traceId: error?.response?.data?.trace_id,
      detail: typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : undefined,
    }
    // Attach structured error info to the rejected error
    if (error) {
      error.apiError = apiError
    }

    return Promise.reject(error)
  }
)

// Status union types
export type TaskStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type IssueStatus = 'open' | 'in_progress' | 'in_review' | 'closed'
export type ContainerStatus = 'created' | 'running' | 'paused' | 'restarting' | 'removing' | 'exited' | 'dead'

// API error type
export interface ApiError {
  status: number
  message: string
  traceId?: string
  detail?: string
}

export type UsageSeverity = 'normal' | 'near_limit' | 'over_limit'

export interface UsageLimitValue {
  mode: 'inherit' | 'custom' | 'unlimited'
  value: number | null
}

export interface CurrentUserUsageSummary {
  user_id: number
  usage: {
    daily_tokens: number
    weekly_tokens: number
    daily_tasks: number
    weekly_tasks: number
  }
  limits: {
    daily_tokens: UsageLimitValue
    weekly_tokens: UsageLimitValue
    daily_tasks: UsageLimitValue
    weekly_tasks: UsageLimitValue
  }
  reset_at: {
    daily: string
    weekly: string
  }
  is_over_limit: boolean
  severity: UsageSeverity
}

export interface AdminUsageSummary {
  daily_tokens: number
  weekly_tokens: number
  daily_tasks: number
  weekly_tasks: number
}

export interface UsageResetAt {
  daily: string
  weekly: string
}

export interface AdminUsageLimitPolicy {
  daily_tokens: UsageLimitValue
  weekly_tokens: UsageLimitValue
  daily_tasks: UsageLimitValue
  weekly_tasks: UsageLimitValue
}

export interface AdminUsageLimitDefaultValue {
  mode: 'custom' | 'unlimited'
  value: number | null
}

export interface AdminUsageLimitUserValue {
  mode: 'inherit' | 'custom' | 'unlimited'
  value: number | null
}

export interface AdminUsageLimitDefaultUpdateRequest {
  daily_tokens: AdminUsageLimitDefaultValue
  weekly_tokens: AdminUsageLimitDefaultValue
  daily_tasks: AdminUsageLimitDefaultValue
  weekly_tasks: AdminUsageLimitDefaultValue
}

export interface AdminUsageLimitUserUpdateRequest {
  daily_tokens: AdminUsageLimitUserValue
  weekly_tokens: AdminUsageLimitUserValue
  daily_tasks: AdminUsageLimitUserValue
  weekly_tasks: AdminUsageLimitUserValue
}

export interface AdminUsageLimitUserRow {
  user_id: number
  username: string
  display_name: string | null
  usage: AdminUsageSummary
  limits: AdminUsageLimitPolicy
  overrides: AdminUsageLimitPolicy
  reset_at: UsageResetAt
}

// Issue types
export interface Issue {
  id: number
  title: string
  description: string | null
  project_id: number
  status: IssueStatus
  closed_via: string | null
  branch_name: string | null
  base_branch: string | null
  target_branch: string | null
  merge_request_iid: number | null
  merge_request_url: string | null
  claude_session_id: string | null
  initiator_user_id: number | null
  initiator_username: string | null
  created_at: string
  updated_at: string
  task_count?: number
  tasks?: Task[]
  totals?: {
    additions: number
    deletions: number
    total_changes: number
    input_tokens: number
    output_tokens: number
  }
}

export interface CreateIssueRequest {
  title: string
  description?: string
  project_id: number
  base_branch?: string
  target_branch?: string
}

export interface IssueListResponse {
  items: Issue[]
  total: number
  page: number
  page_size: number
}

// Task types
export interface Task {
  id: number
  issue_id: number | null
  project_id: number
  project_name?: string | null
  project_path_with_namespace?: string | null
  project_url?: string | null
  user_prompt: string
  initiator_user_id?: number | null
  initiator_gitlab_user_id?: number | null
  initiator_username?: string | null
  status: TaskStatus
  priority: number
  is_retry: boolean
  retry_source_task_id: number | null
  scheduled_at: string | null
  container_id: string | null
  container_name: string | null
  commit_sha: string | null
  error_message: string | null
  additions: number
  deletions: number
  total_changes: number
  input_tokens: number | null
  output_tokens: number | null
  model_name?: string | null
  merge_request_title?: string | null
  provider_id: number | null
  provider_name?: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  issue?: {
    id: number
    title: string
    branch_name: string | null
    base_branch: string | null
    target_branch: string | null
    merge_request_iid: number | null
    merge_request_url: string | null
  }
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

// AI Provider types
export interface AIProvider {
  id: number
  name: string
  base_url: string
  api_key_configured: boolean
  model: string
  max_turns: number
  system_prompt: string | null
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface CreateProviderRequest {
  name: string
  base_url: string
  api_key?: string
  model: string
  max_turns?: number
  system_prompt?: string
}

export interface UpdateProviderRequest {
  name?: string
  base_url?: string
  api_key?: string
  clear_api_key?: boolean
  model?: string
  max_turns?: number
  system_prompt?: string | null
  clear_system_prompt?: boolean
}

// Request types
export interface CreateTaskRequest {
  issue_id: number
  user_prompt?: string
  priority?: number
  delay_seconds?: number
  scheduled_datetime?: string
  provider_id?: number | null
}

export interface RescheduleTaskRequest {
  scheduled_datetime: string
}

export interface TaskLog {
  id: number
  task_id: number
  log_level: string
  log_type?: string | null
  metadata?: string | null
  message: string
  created_at: string
}

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  output: string | null
  error: boolean
  /** ISO timestamp present on real-time individual log entries (log_type='tool_call'). */
  timestamp?: string
}

export interface TaskStats {
  additions: number
  deletions: number
  total: number
}

export interface Container {
  id: string
  name: string
  status: ContainerStatus
  task_id: number | null
  project_id: number | null
  issue_id: number | null
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
  completed_24h: number
  failed_cancelled_24h: number
  running_long_30min: number
  issues?: {
    total: number
    by_status: Record<string, number>
  }
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

export interface AnalyticsInitiatorOption {
  initiator_username: string
  initiator_gitlab_user_id: number | null
  task_count: number
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

export interface AnalyticsStatusRow {
  status: IssueStatus | TaskStatus
  count: number
  share: number
}

export interface AnalyticsProviderRow {
  provider_id: number | null
  provider_name: string | null
  provider_model: string | null
  task_count: number
  completed_task_count: number
  failed_task_count: number
  cancelled_task_count: number
  finished_task_count: number
  success_rate: number | null
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  avg_tokens_per_task: number | null
  avg_tokens_per_second: number | null
  avg_tokens_per_changed_line: number | null
  avg_execution_seconds: number | null
  avg_execution_seconds_per_changed_line: number | null
}

export interface AnalyticsProviderSummary {
  active_provider_count: number
  provider_covered_task_count: number
  provider_covered_total_tokens: number
  provider_success_rate: number | null
}

export interface AnalyticsProviderChartPoint {
  provider_id: number | null
  label: string
  value: number
}

export interface AnalyticsProviderChartSeries {
  success_rate: AnalyticsProviderChartPoint[]
  avg_tokens_per_second: AnalyticsProviderChartPoint[]
  avg_tokens_per_changed_line: AnalyticsProviderChartPoint[]
  avg_execution_seconds_per_changed_line: AnalyticsProviderChartPoint[]
}

export interface AnalyticsResponse {
  window_days: number
  generated_at: string
  summary: AnalyticsSummary
  provider_summary: AnalyticsProviderSummary
  available_initiators: AnalyticsInitiatorOption[]
  projects: AnalyticsProjectRow[]
  initiators: AnalyticsInitiatorRow[]
  providers: AnalyticsProviderRow[]
  provider_chart_series: AnalyticsProviderChartSeries
  trends: AnalyticsTrendPoint[]
  priority_waits: AnalyticsPriorityWaitRow[]
  issue_status_breakdown: AnalyticsStatusRow[]
  task_status_breakdown: AnalyticsStatusRow[]
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
  worker_volume_mounts: string
  worker_environment_variables: WorkerEnvironmentVariable[]
  maven_cache_host_path: string
  maven_settings_host_path: string
  slot_max_tasks: number
  slot_max_tasks_enforce: boolean
}

export interface WorkerEnvironmentVariable {
  id?: number
  key: string
  value: string
  is_secret: boolean
  value_configured: boolean
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

export type MattermostNotificationTargetType = 'channel' | 'initiator_dm'
export type MattermostNotificationEventType =
  | 'task_completed'
  | 'task_failed'
  | 'task_rescheduled'
  | 'task_execute_now'
  | 'task_retry_scheduled'
  | 'task_cancelled'
export type MattermostNotificationFieldKey =
  | 'task_id'
  | 'project'
  | 'issue'
  | 'merge_request'
  | 'initiator'
  | 'status'
  | 'branch'
  | 'target_branch'
  | 'scheduled_at'
  | 'schedule_change'
  | 'error'
  | 'task_link'

export interface MattermostIntegrationConfig {
  mattermost_server_url: string
  mattermost_bot_token_configured: boolean
}

export interface MattermostNotificationProfile {
  id: number
  name: string
  enabled: boolean
  target_type: MattermostNotificationTargetType
  channel_id: string | null
  mention_in_channel: boolean
  event_types: MattermostNotificationEventType[]
  field_keys: MattermostNotificationFieldKey[]
  created_at: string
  updated_at: string
}

export interface MattermostChannelTarget {
  channel_id: string
  team_name: string
  team_display_name: string
  channel_name: string
  channel_display_name: string
}

export interface MattermostNotificationConfig {
  integration: MattermostIntegrationConfig
  profiles: MattermostNotificationProfile[]
}

export interface MattermostIntegrationUpdate {
  mattermost_server_url?: string
  mattermost_bot_token?: string
  clear_mattermost_bot_token?: boolean
}

export interface MattermostConnectionTestResult {
  server_url: string
  username: string
}

export interface MattermostNotificationProfilePayload {
  name: string
  enabled: boolean
  target_type: MattermostNotificationTargetType
  channel_id?: string | null
  mention_in_channel: boolean
  event_types: MattermostNotificationEventType[]
  field_keys: MattermostNotificationFieldKey[]
}

export interface MattermostResolveChannelTargetPayload {
  team_name: string
  channel_name: string
}

export interface RuntimeConfigUpdate
  extends Partial<
    Omit<
      RuntimeConfig,
      'alert_webhook_url_configured' | 'anthropic_api_key_configured' | 'worker_environment_variables'
    >
  > {
  alert_webhook_url?: string
  clear_alert_webhook_url?: boolean
  anthropic_api_key?: string
  clear_anthropic_api_key?: boolean
  worker_volume_mounts?: string
  worker_environment_variables?: WorkerEnvironmentVariableUpdate[]
  maven_cache_host_path?: string
  maven_settings_host_path?: string
}

export interface WorkerEnvironmentVariableUpdate {
  id?: number
  key: string
  value: string
  is_secret: boolean
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
  merge_requests_events: boolean | null
  managed_secret_configured: boolean
  global_secret_fallback_configured: boolean
  secret_mode: 'project' | 'global_fallback' | 'none' | string
}

export interface WebhookEvent {
  id: number
  event_type: string
  event_action: string | null
  project_id: number
  merge_request_iid: number | null
  issue_id: number | null
  source_ip: string | null
  result: string
  result_detail: string | null
  payload_summary: Record<string, unknown> | null
  created_at: string
}

export interface WebhookEventsResponse {
  items: WebhookEvent[]
  total: number
  page: number
  page_size: number
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
  system_initialized?: boolean
}

export interface AdminUser {
  id: number
  gitlab_user_id: number | null
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

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export async function getTasksPaginated(params: {
  page: number
  page_size?: number
  status?: string
  project_id?: number
  initiator_username?: string
  priority?: string
  search?: string
  created_after?: string
  created_before?: string
  sort_by?: string
  sort_order?: string
}): Promise<PaginatedResponse<Task>> {
  const response = await api.get('/tasks', { params })
  return response.data
}

export async function getScheduledTasks(params?: { project_id?: number; hour_start?: string }): Promise<Task[]> {
  const response = await api.get('/tasks/scheduled', { params })
  return response.data
}

export interface ScheduledStatsSummary {
  total: number
  ready_now: number
  next_24h: number
  later: number
  queued_count: number
  running_count: number
  busiest_hour_count: number
  busiest_hour_label: string
}

export interface HourlyBucket {
  hour_start: string
  count: number
}

export interface ScheduledStatsResponse {
  summary: ScheduledStatsSummary
  hourly_distribution: HourlyBucket[]
  max_count: number
}

export async function getScheduledStats(params?: { project_id?: number }): Promise<ScheduledStatsResponse> {
  const response = await api.get('/stats/scheduled', { params })
  return response.data
}

export interface SlotCapacityInfo {
  hour_start: string
  hour_end: string
  count: number
  max: number
  is_full: boolean
  enforce: boolean
}

export async function getSlotCapacity(scheduledAt: string): Promise<SlotCapacityInfo> {
  const response = await api.get('/tasks/slot-capacity', { params: { scheduled_at: scheduledAt } })
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

/**
 * Open an SSE connection to stream task log entries in real-time.
 *
 * @param id - Task ID
 * @param sinceId - Only receive entries with id > sinceId (for resuming a stream)
 * @param onLog - Callback invoked for each new log entry
 * @param onDone - Callback invoked when the task reaches a terminal state
 * @returns EventSource instance (call .close() to stop streaming)
 */
export function streamTaskLogs(
  id: number,
  sinceId: number,
  onLog: (log: TaskLog) => void,
  onDone?: () => void,
): EventSource {
  const url = `/api/tasks/${id}/log-stream?since_id=${sinceId}`
  const source = new EventSource(url)

  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.error) {
        console.error(`[streamTaskLogs] server error: ${data.error}`)
      } else {
        onLog(data as TaskLog)
      }
    } catch (e) {
      console.warn('[streamTaskLogs] failed to parse SSE message', e)
    }
  }

  source.addEventListener('done', () => {
    source.close()
    onDone?.()
  })

  source.onerror = (e) => {
    console.warn('[streamTaskLogs] SSE connection error', e)
  }

  return source
}

export async function getTaskContainerLogs(id: number, source?: 'db' | 'auto'): Promise<{
  container_id: string | null
  container_status: string
  logs: string
  status: string
}> {
  const params = source ? { source } : {}
  const response = await api.get(`/tasks/${id}/container-logs`, { params })
  return response.data
}

export async function getTaskStats(id: number): Promise<TaskStats> {
  const response = await api.get(`/tasks/${id}/stats`)
  return response.data
}

export async function cancelTask(id: number): Promise<void> {
  await api.post(`/tasks/${id}/cancel`)
}

export async function retryTask(id: number, scheduledDatetime?: string): Promise<Task> {
  const body = scheduledDatetime ? { scheduled_datetime: scheduledDatetime } : undefined
  const { data } = await api.post(`/tasks/${id}/retry`, body)
  return data
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

export async function getStats(params?: {
  my?: boolean
}): Promise<Stats> {
  const response = await api.get('/stats', { params })
  return response.data
}

export interface ActivityHeatmapEntry {
  date: string
  count: number
}

export async function getActivityHeatmap(days = 365, my = false): Promise<ActivityHeatmapEntry[]> {
  const res = await api.get<ActivityHeatmapEntry[]>('/stats/activity-heatmap', {
    params: { days, ...(my ? { my: true } : {}) },
  })
  return res.data
}

export async function getAnalytics(
  days: number,
  projectId?: number | null,
  initiatorUsername?: string | null
): Promise<AnalyticsResponse> {
  const response = await api.get('/stats/analytics', {
    params: {
      days,
      project_id: projectId ?? undefined,
      initiator_username: initiatorUsername || undefined
    }
  })
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
  const response = await api.post('/config/oidc/test', { auth }, {
    headers: { 'X-Skip-Auth-Redirect': 'true' }
  })
  return response.data
}

export async function testGitLabConfig(
  integration: IntegrationConfigUpdate,
): Promise<GitLabConfigTestResult> {
  const response = await api.post('/config/gitlab/test', { integration }, {
    headers: { 'X-Skip-Auth-Redirect': 'true' }
  })
  return response.data
}

export async function invalidateProjectCache(): Promise<{ status: string; message: string }> {
  const response = await api.post('/config/gitlab/projects/cache/invalidate')
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

export async function getWebhookEvents(params: {
  page?: number
  page_size?: number
  event_type?: string
  result?: string
  project_id?: number
} = {}): Promise<WebhookEventsResponse> {
  const response = await api.get('/webhook/events', { params })
  return response.data
}

export async function getOidcDiagnostics(): Promise<OidcDiagnosticsResult> {
  const response = await api.get('/config/oidc/diagnostics', {
    // Skip global 401 interceptor redirect for OIDC diagnostics
    // This allows the component to handle auth errors gracefully
    headers: { 'X-Skip-Auth-Redirect': 'true' }
  })
  return response.data
}

export async function getMattermostNotificationConfig(): Promise<MattermostNotificationConfig> {
  const response = await api.get('/config/notifications')
  return response.data
}

export async function updateMattermostIntegration(
  integration: MattermostIntegrationUpdate
): Promise<MattermostNotificationConfig> {
  const response = await api.patch('/config/notifications/integration', integration)
  return response.data
}

export async function testMattermostIntegration(
  integration: MattermostIntegrationUpdate
): Promise<MattermostConnectionTestResult> {
  const response = await api.post('/config/notifications/test', { integration })
  return response.data
}

export async function createMattermostNotificationProfile(
  payload: MattermostNotificationProfilePayload
): Promise<MattermostNotificationProfile> {
  const response = await api.post('/config/notifications/profiles', payload)
  return response.data
}

export async function updateMattermostNotificationProfile(
  profileId: number,
  payload: MattermostNotificationProfilePayload
): Promise<MattermostNotificationProfile> {
  const response = await api.patch(`/config/notifications/profiles/${profileId}`, payload)
  return response.data
}

export async function deleteMattermostNotificationProfile(profileId: number): Promise<void> {
  await api.delete(`/config/notifications/profiles/${profileId}`)
}

export async function resolveMattermostChannelTarget(
  payload: MattermostResolveChannelTargetPayload
): Promise<MattermostChannelTarget> {
  const response = await api.post('/config/notifications/channel-targets/resolve', payload)
  return response.data
}

export async function getMattermostChannelTarget(channelId: string): Promise<MattermostChannelTarget> {
  const response = await api.get(`/config/notifications/channel-targets/${encodeURIComponent(channelId)}`)
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

export async function getAdminUsageLimitDefault(): Promise<AdminUsageLimitPolicy> {
  const response = await api.get('/admin/usage-limits/default')
  return response.data
}

export async function updateAdminUsageLimitDefault(
  payload: AdminUsageLimitDefaultUpdateRequest
): Promise<AdminUsageLimitPolicy> {
  const response = await api.patch('/admin/usage-limits/default', payload)
  return response.data
}

export async function listAdminUsageLimitUsers(): Promise<AdminUsageLimitUserRow[]> {
  const response = await api.get('/admin/usage-limits/users')
  return response.data
}

export async function updateAdminUsageLimitUser(
  userId: number,
  payload: AdminUsageLimitUserUpdateRequest
): Promise<AdminUsageLimitUserRow> {
  const response = await api.patch(`/admin/usage-limits/users/${userId}`, payload)
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

// Prompt Template APIs
export interface PromptTemplate {
  id: number
  name: string
  content: string
  variable_tips?: Record<string, string>
  is_active: boolean
  created_at: string
  updated_at: string
}

export async function getPromptTemplates(): Promise<PromptTemplate[]> {
  const response = await api.get('/prompt-templates')
  return response.data
}

export async function createPromptTemplate(template: { name: string; content: string; variable_tips?: Record<string, string>; is_active?: boolean }): Promise<PromptTemplate> {
  const response = await api.post('/prompt-templates', template)
  return response.data
}

export async function updatePromptTemplate(templateId: number, template: { name?: string; content?: string; variable_tips?: Record<string, string>; is_active?: boolean }): Promise<PromptTemplate> {
  const response = await api.put(`/prompt-templates/${templateId}`, template)
  return response.data
}

export async function deletePromptTemplate(templateId: number): Promise<void> {
  await api.delete(`/prompt-templates/${templateId}`)
}

// Issue APIs
export async function getIssues(params?: {
  status?: string
  project_id?: number
  initiator_user_id?: number
  search?: string
  created_after?: string
  created_before?: string
  sort_by?: string
  sort_order?: string
  page?: number
  page_size?: number
}): Promise<IssueListResponse> {
  const response = await api.get('/issues', { params })
  return response.data
}

export async function getIssue(id: number): Promise<Issue> {
  const response = await api.get(`/issues/${id}`)
  return response.data
}

export async function createIssue(data: CreateIssueRequest): Promise<Issue> {
  const response = await api.post('/issues', data)
  return response.data
}

export async function updateIssue(id: number, data: Partial<{
  title: string
  description: string
  status: string
}>): Promise<Issue> {
  const response = await api.patch(`/issues/${id}`, data)
  return response.data
}

export async function closeIssue(id: number): Promise<Issue> {
  const response = await api.post(`/issues/${id}/close`)
  return response.data
}

export async function deleteIssue(id: number): Promise<void> {
  await api.delete(`/issues/${id}`)
}

// AI Provider API functions
export async function getProviders(): Promise<AIProvider[]> {
  const { data } = await api.get('/providers')
  return data
}

export async function getProvider(id: number): Promise<AIProvider> {
  const { data } = await api.get(`/providers/${id}`)
  return data
}

export async function createProvider(request: CreateProviderRequest): Promise<AIProvider> {
  const { data } = await api.post('/providers', request)
  return data
}

export async function updateProvider(id: number, request: UpdateProviderRequest): Promise<AIProvider> {
  const { data } = await api.patch(`/providers/${id}`, request)
  return data
}

export async function deleteProvider(id: number): Promise<void> {
  await api.delete(`/providers/${id}`)
}

export async function setDefaultProvider(id: number): Promise<AIProvider> {
  const { data } = await api.post(`/providers/${id}/set-default`)
  return data
}

export async function getMyUsageSummary(): Promise<CurrentUserUsageSummary> {
  const { data } = await api.get('/usage/me')
  return data
}

export default api
