import { api } from './client'
import type { Task, TaskStatus } from './tasks'

export * from './client'
export * from './filterOptions'
export * from './tasks'

// Status union types
export type IssueStatus = 'open' | 'in_progress' | 'in_review' | 'closed'
export type ContainerStatus = 'created' | 'running' | 'paused' | 'restarting' | 'removing' | 'exited' | 'dead'

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
    duration_seconds: number
  }
  // New fields for branch deletion handling
  delete_branch_on_close: boolean
  branch_deleted: boolean
  ci_auto_repair_enabled: boolean
  worker_profile_id: number
  default_provider_id: number | null
  git_clone_depth: number | null
  git_clone_filter: 'blob:none' | null
  worker_profile_name?: string | null
  default_provider_name?: string | null
}

export interface CreateIssueRequest {
  title: string
  description?: string
  project_id: number
  base_branch?: string
  target_branch?: string
  // Option to delete branch when a webhook auto-closes the issue
  delete_branch_on_close?: boolean
  ci_auto_repair_enabled?: boolean
  worker_profile_id: number
  default_provider_id?: number | null
  git_clone_depth?: number | null
  git_clone_filter?: 'blob:none' | null
}

export interface CloseIssueRequest {
  branch_action: 'keep' | 'delete'
  delete_branch: boolean
}

export interface IssueListResponse {
  items: Issue[]
  total: number
  page: number
  page_size: number
}

// Project and Branch types for manual task creation
export interface Project {
  id: number
  name: string
  path_with_namespace: string
  default_branch?: string
  web_url?: string | null
  description?: string | null
}

export interface ProjectCIAutoRepairAvailability {
  project_id: number
  webhook_status: 'configured' | 'missing' | 'needs_attention' | 'error' | string
  webhook_status_issues: string[]
  ci_auto_repair_available: boolean
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
  provider_kind?: string
  wire_protocol?: string
  provider_driver?: string | null
  provider_options?: Record<string, unknown>
  credential_ref?: string | null
  credential_status?: string | null
  model: string
  max_turns: number
  system_prompt: string | null
  is_default: boolean
  is_disabled: boolean
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
  is_disabled?: boolean
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
  is_disabled?: boolean
}

export interface WorkerProfileEnvironmentVariable {
  id?: number
  key: string
  value: string | null
  is_secret: boolean
  value_configured: boolean
}

export interface WorkerProfileEnvironmentVariableUpdate {
  id?: number
  key: string
  value: string
  is_secret: boolean
}

export interface WorkerProfileMount {
  host_path: string
  container_path: string
  mode: 'ro' | 'rw'
}

export interface WorkerProfile {
  id: number
  name: string
  description: string | null
  enabled: boolean
  is_default: boolean
  image: string
  runtime_mode: 'baked_image' | 'mounted_kit'
  worker_kit_version: string | null
  worker_kit_path: string | null
  docker_host?: string | null
  docker_tls_ca?: string | null
  docker_tls_cert?: string | null
  docker_tls_key?: string | null
  codegraph_enabled: boolean
  volume_mounts: WorkerProfileMount[]
  environment_variables: WorkerProfileEnvironmentVariable[]
  default_skill_ids: number[]
  pre_script: string
  post_script: string
  default_execute_run_instruction_template: string
  default_plan_run_instruction_template: string
  ci_auto_repair_run_instruction_template: string
  enabled_harnesses?: string[]
  default_harness_key?: string
  harness_constraints?: Record<string, unknown>
  image_digest?: string | null
  created_at: string
  updated_at: string
}

export interface WorkerProfilePayload {
  name?: string
  description?: string | null
  enabled?: boolean
  image?: string
  runtime_mode?: 'baked_image' | 'mounted_kit'
  worker_kit_version?: string | null
  worker_kit_path?: string | null
  docker_host?: string | null
  docker_tls_ca?: string | null
  docker_tls_cert?: string | null
  docker_tls_key?: string | null
  codegraph_enabled?: boolean
  volume_mounts?: WorkerProfileMount[]
  environment_variables?: WorkerProfileEnvironmentVariableUpdate[]
  default_skill_ids?: number[]
  pre_script?: string
  post_script?: string
  default_execute_run_instruction_template?: string
  default_plan_run_instruction_template?: string
  ci_auto_repair_run_instruction_template?: string
}

export interface DockerConnectionTestResult {
  docker_host: string
  server_version: string | null
  architecture: string | null
  operating_system: string | null
  elapsed_ms: number
}

export interface SkillSummary {
  id: number
  name: string
  description: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface SkillFile {
  path: string
  content_base64: string
  executable: boolean
}

export interface Skill extends SkillSummary {
  skill_md: string
  files: SkillFile[]
}

export type SkillOption = Pick<SkillSummary, 'id' | 'name' | 'description'> & {
  version_id: number
}

export interface SkillPayload {
  name: string
  skill_md: string
  files: SkillFile[]
  enabled?: boolean
}

export interface Container {
  id: string
  name: string
  status: ContainerStatus
  task_id: number | null
  project_id: number | null
  issue_id: number | null
  docker_target?: string
  created_at: string
}

export interface DockerTargetError {
  docker_target: string
}

export interface ContainerOverview {
  containers: Container[]
  target_errors: DockerTargetError[]
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
  total_execution_seconds: number
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
  total_execution_seconds: number
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
  total_execution_seconds: number
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
  worker_pre_script: string
  worker_post_script: string
  worker_environment_variables: WorkerEnvironmentVariable[]
  worker_workspace_host_path: string
  worker_workspace_retention_days: number
  worker_artifacts_max_total_bytes: number
  worker_artifacts_max_file_bytes: number
  worker_artifacts_max_entries: number
  worker_runtime_archive_retention_days: number
  slot_max_tasks: number
  slot_max_tasks_enforce: boolean
  ci_auto_repair_max_attempts: number
  announcement_enabled: boolean
  announcement_text: string
  announcement_level: string
  default_execute_run_instruction_template: string
  default_plan_run_instruction_template: string
  ci_auto_repair_run_instruction_template: string
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
  session_retention_days: number
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
      | 'alert_webhook_url_configured'
      | 'anthropic_api_key_configured'
      | 'worker_environment_variables'
      | 'worker_workspace_host_path'
    >
  > {
  alert_webhook_url?: string
  clear_alert_webhook_url?: boolean
  anthropic_api_key?: string
  clear_anthropic_api_key?: boolean
  worker_volume_mounts?: string
  worker_pre_script?: string
  worker_post_script?: string
  worker_environment_variables?: WorkerEnvironmentVariableUpdate[]
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
      'gitlab_bot_token_configured' | 'gitlab_admin_token_configured'
    >
  > {
  gitlab_bot_token?: string
  clear_gitlab_bot_token?: boolean
  gitlab_admin_token?: string
  clear_gitlab_admin_token?: boolean
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
  pipeline_events: boolean | null
  managed_secret_configured: boolean
  secret_mode: 'project' | 'none' | string
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

export interface CIFailureJob {
  id: number
  gitlab_job_id: number
  name: string
  stage: string | null
  status: string
  failure_reason: string | null
  allow_failure: boolean
  web_url: string | null
  trace_path: string | null
  trace_size_bytes: number
  is_root_cause: boolean
  is_downstream_suppressed: boolean
  classification: 'code' | 'infra' | 'unknown' | string
  created_at: string | null
}

export interface CIFailureRun {
  id: number
  webhook_event_id: number | null
  project_id: number
  issue_id: number | null
  merge_request_iid: number | null
  source_branch: string | null
  target_branch: string | null
  pipeline_id: number
  pipeline_sha: string
  pipeline_ref: string | null
  pipeline_status: string
  pipeline_url: string | null
  status: 'collecting' | 'collected' | 'task_created' | 'ignored' | 'failed' | string
  root_cause_strategy: string
  bundle_available: boolean
  repair_task_id: number | null
  ignored_reason: string | null
  error_message: string | null
  collection_attempts: number
  created_at: string | null
  updated_at: string | null
  jobs: CIFailureJob[] | null
  logs: CIFailureRunLog[] | null
}

export interface CIFailureRunLog {
  id: number
  ci_failure_run_id: number
  issue_id: number | null
  task_id: number | null
  step: string
  status: string
  message: string | null
  details: Record<string, unknown> | null
  created_at: string | null
}

export interface CIFailureRunsResponse {
  items: CIFailureRun[]
  total: number
  page: number
  page_size: number
}

export interface CIFailureRunLogsResponse {
  items: CIFailureRunLog[]
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
export async function getContainers(): Promise<ContainerOverview | Container[]> {
  const response = await api.get('/containers', {
    params: { include_target_status: true },
  })
  return response.data
}

export async function getContainerLogs(containerId: string, taskId?: number): Promise<string> {
  const response = await api.get(`/containers/${containerId}/logs`, {
    params: taskId == null ? undefined : { task_id: taskId },
  })
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

export interface CleanupSystemDataRequest {
  older_than_days?: number | null
  force: boolean
}

export interface CleanupSystemDataResult {
  deleted_issues: number
  deleted_tasks: number
  skipped_active_issues: number
  skipped_active_tasks: number
  deleted_archives: number
  missing_archives: number
  deleted_workspaces: number
  container_cleanup_errors: Array<{ task_id: number; container_name: string; error: string }>
  file_cleanup_errors: Array<{ kind: string; path: string; error: string }>
}

export async function cleanupSystemData(request: CleanupSystemDataRequest): Promise<CleanupSystemDataResult> {
  const response = await api.post('/config/maintenance/cleanup-system-data', request)
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

export async function getIssueWebhookEvents(
  issueId: number,
  params: { page?: number; page_size?: number } = {},
): Promise<WebhookEventsResponse> {
  const response = await api.get(`/issues/${issueId}/webhook-events`, { params })
  return response.data
}

export async function getIssueCIFailures(
  issueId: number,
  params: { page?: number; page_size?: number } = {},
): Promise<CIFailureRunsResponse> {
  const response = await api.get(`/issues/${issueId}/ci-failures`, { params })
  return response.data
}

export async function getCIFailureLogs(ciFailureRunId: number): Promise<CIFailureRunLogsResponse> {
  const response = await api.get(`/ci-failures/${ciFailureRunId}/logs`)
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

export async function getProjectCIAutoRepairAvailability(
  projectId: number,
): Promise<ProjectCIAutoRepairAvailability> {
  const response = await api.get(`/projects/${projectId}/ci-auto-repair-availability`)
  return response.data
}

export async function getBranches(projectId: number): Promise<Branch[]> {
  const response = await api.get(`/projects/${projectId}/branches`)
  return response.data
}

// Prompt Template APIs
export interface PromptTemplate {
  id: number
  name: string
  content: string
  variable_tips?: Record<string, string>
  tags?: string[]
  is_active: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export async function getPromptTemplates(): Promise<PromptTemplate[]> {
  const response = await api.get('/prompt-templates')
  return response.data
}

export async function createPromptTemplate(template: { name: string; content: string; variable_tips?: Record<string, string>; tags?: string[]; is_active?: boolean }): Promise<PromptTemplate> {
  const response = await api.post('/prompt-templates', template)
  return response.data
}

export async function updatePromptTemplate(templateId: number, template: { name?: string; content?: string; variable_tips?: Record<string, string>; tags?: string[]; is_active?: boolean }): Promise<PromptTemplate> {
  const response = await api.put(`/prompt-templates/${templateId}`, template)
  return response.data
}

export async function reorderPromptTemplates(templateIds: number[]): Promise<PromptTemplate[]> {
  const response = await api.put('/prompt-templates/reorder', { template_ids: templateIds })
  return response.data
}

export async function deletePromptTemplate(templateId: number): Promise<void> {
  await api.delete(`/prompt-templates/${templateId}`)
}

// Issue APIs
export async function getIssues(params?: {
  status?: string
  project_id?: string | number
  initiator?: string
  initiator_user_id?: string | number
  initiator_username?: string
  has_mr?: boolean | string
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
  ci_auto_repair_enabled: boolean
  default_provider_id: number | null
}>): Promise<Issue> {
  const response = await api.patch(`/issues/${id}`, data)
  return response.data
}

export async function closeIssue(
  id: number,
  request: CloseIssueRequest = { branch_action: 'keep', delete_branch: false }
): Promise<Issue> {
  const response = await api.post(`/issues/${id}/close`, request)
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

export async function getWorkerProfiles(): Promise<WorkerProfile[]> {
  const { data } = await api.get('/worker-profiles')
  return data
}

export async function getAdminWorkerProfiles(): Promise<WorkerProfile[]> {
  const { data } = await api.get('/worker-profiles/admin')
  return data
}

export async function testWorkerDockerConnection(
  payload: Pick<
    WorkerProfilePayload,
    'docker_host' | 'docker_tls_ca' | 'docker_tls_cert' | 'docker_tls_key'
  >
): Promise<DockerConnectionTestResult> {
  const { data } = await api.post('/worker-profiles/test-docker-connection', payload)
  return data
}

export async function createWorkerProfile(payload: WorkerProfilePayload): Promise<WorkerProfile> {
  const { data } = await api.post('/worker-profiles', payload)
  return data
}

export async function updateWorkerProfile(
  profileId: number,
  payload: WorkerProfilePayload
): Promise<WorkerProfile> {
  const { data } = await api.patch(`/worker-profiles/${profileId}`, payload)
  return data
}

export async function setDefaultWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const { data } = await api.post(`/worker-profiles/${profileId}/set-default`)
  return data
}

export async function disableWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const { data } = await api.post(`/worker-profiles/${profileId}/disable`)
  return data
}

export async function enableWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const { data } = await api.patch(`/worker-profiles/${profileId}`, { enabled: true })
  return data
}

export async function deleteWorkerProfile(profileId: number): Promise<void> {
  await api.delete(`/worker-profiles/${profileId}`)
}

export async function duplicateWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const { data } = await api.post(`/worker-profiles/${profileId}/duplicate`)
  return data
}

export async function getSkills(): Promise<SkillOption[]> {
  const { data } = await api.get('/skills')
  return data
}

export async function getAdminSkills(): Promise<SkillSummary[]> {
  const { data } = await api.get('/skills/admin')
  return data
}

export async function getAdminSkill(skillId: number): Promise<Skill> {
  const { data } = await api.get(`/skills/${skillId}/admin`)
  return data
}

export async function downloadSkill(skillId: number): Promise<Blob> {
  const { data } = await api.get(`/skills/${skillId}/download`, { responseType: 'blob' })
  return data
}

export async function createSkill(payload: SkillPayload): Promise<Skill> {
  const { data } = await api.post('/skills', payload)
  return data
}

export async function updateSkill(
  skillId: number,
  payload: Partial<SkillPayload>
): Promise<Skill> {
  const { data } = await api.patch(`/skills/${skillId}`, payload)
  return data
}

export async function setSkillEnabled(skillId: number, enabled: boolean): Promise<SkillSummary> {
  const action = enabled ? 'enable' : 'disable'
  const { data } = await api.post(`/skills/${skillId}/${action}`)
  return data
}

export async function deleteSkill(skillId: number): Promise<void> {
  await api.delete(`/skills/${skillId}`)
}

export async function getMyUsageSummary(): Promise<CurrentUserUsageSummary> {
  const { data } = await api.get('/usage/me')
  return data
}

export async function deleteIssueBranch(id: number): Promise<Issue> {
  const response = await api.post(`/issues/${id}/delete-branch`)
  return response.data
}

export interface AnnouncementInfo {
  enabled: boolean
  text: string
  level: string // 'info' | 'warning' | 'error' | 'success'
}

export async function getAnnouncement(): Promise<AnnouncementInfo> {
  const response = await api.get('/announcement')
  return response.data
}

export default api
