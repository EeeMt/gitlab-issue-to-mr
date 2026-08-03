import { api } from './client'

export type TaskStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface TaskModelServiceSummary {
  configuration_source: 'execution_snapshot' | 'current_provider' | 'unavailable'
  provider_config_available: boolean
  provider_id: number | null
  provider_name: string | null
  base_url: string | null
  configured_model: string | null
  actual_model: string | null
  max_turns: number | null
  system_prompt: string | null
  api_key_configured: boolean
  configuration_captured_at: string | null
}

export interface TaskWorkerRuntimeMount {
  source: 'worker_kit' | 'profile'
  host_path: string
  container_path: string
  mode: string
}

export interface TaskWorkerRuntimeEnvironmentVariable {
  key: string
  is_secret: boolean
  value_configured: boolean
}

export interface TaskWorkerRuntimeSummary {
  snapshot_available: boolean
  worker_profile_id: number | null
  worker_profile_name: string | null
  image: string | null
  runtime_mode: 'baked_image' | 'mounted_kit' | string | null
  worker_kit_version: string | null
  worker_kit_path: string | null
  codegraph_enabled: boolean
  mounts: TaskWorkerRuntimeMount[]
  environment_variables: TaskWorkerRuntimeEnvironmentVariable[]
  skills: Array<{
    id: number | null
    name: string
    description: string
  }>
  skill_selection_source: 'profile' | 'task'
  pre_script_configured: boolean
  post_script_configured: boolean
  snapshot_created_at: string | null
}

export interface TaskSkillSnapshot {
  id: number | null
  name: string
  description: string
  version_id: number
}

export interface Task {
  id: number
  issue_id: number
  project_id: number
  project_name?: string | null
  project_path_with_namespace?: string | null
  project_url?: string | null
  user_prompt: string
  run_instruction_template?: string | null
  rendered_prompt?: string | null
  rendered_prompt_at?: string | null
  initiator_user_id?: number | null
  initiator_gitlab_user_id?: number | null
  initiator_username?: string | null
  status: TaskStatus
  priority: number
  is_retry: boolean
  retry_source_task_id: number | null
  trigger_source: 'manual' | 'retry' | 'follow_up' | 'ci_auto_repair' | string
  ci_failure_run_id: number | null
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
  commit_message?: string | null
  require_changes: boolean
  task_mode: 'execute' | 'plan'
  session_mode: 'continue' | 'fresh'
  input_session_id: string | null
  output_session_id: string | null
  provider_id: number | null
  provider_name?: string | null
  worker_profile_id: number | null
  worker_profile_name?: string | null
  worker_image?: string | null
  worker_runtime_mode?: 'baked_image' | 'mounted_kit' | string | null
  worker_kit_version?: string | null
  worker_snapshot_created_at?: string | null
  skill_ids?: number[]
  skill_names?: string[]
  skill_snapshots?: TaskSkillSnapshot[]
  skill_selection_source: 'profile' | 'task'
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  is_manually_overridden?: boolean
  override_reason?: string | null
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

export interface CreateTaskRequest {
  issue_id: number
  user_prompt?: string
  priority?: number
  delay_seconds?: number
  scheduled_datetime?: string
  provider_id?: number | null
  harness_key?: string
  require_changes?: boolean
  task_mode?: 'execute' | 'plan'
  session_mode?: 'continue' | 'fresh'
  run_instruction_template?: string
  skill_ids?: number[]
}

export interface RescheduleTaskRequest {
  scheduled_datetime: string
}

export interface UpdateTaskRequest {
  user_prompt?: string
  priority?: number
  provider_id?: number | null
  require_changes?: boolean
  task_mode?: 'execute' | 'plan'
  run_instruction_template?: string
  skill_ids?: number[] | null
}

export interface TaskLog {
  id: number
  task_id: number
  log_level: string
  log_type?: string | null
  metadata?: unknown
  message: string
  created_at: string
}

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  output: string | null
  error: boolean
  timestamp?: string
  duration_ms?: number
  input_payload_id?: number
  input_preview?: string
  input_truncated?: boolean
  output_payload_id?: number
  output_preview?: string
  output_truncated?: boolean
  output_char_count?: number
}

export interface TaskPayloadResponse {
  id: number
  payload_kind: string
  content: string
  encoding: string
  char_count: number
  byte_count: number
}

export interface TaskStats {
  additions: number
  deletions: number
  total: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
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
  slot_max_tasks: number
  slot_max_tasks_enforce: boolean
}

export interface SlotCapacityInfo {
  hour_start: string
  hour_end: string
  count: number
  max: number
  is_full: boolean
  enforce: boolean
}

export interface TaskContainerLogsResponse {
  container_id: string | null
  container_status?: string
  logs: string
  status: string
  source?: 'db'
  last_sequence_no?: number
  raw_logs_finalized?: boolean
  logs_truncated?: boolean
}

export interface TaskArchive {
  archive_name: string
  archive_size_bytes: number
  created_at: string
  file_exists: boolean
}

export interface RunInstructionTemplateMetadata {
  content: string
  available_placeholders: string[]
  known_placeholders?: string[]
}

export interface RunInstructionTemplateDefaults {
  execute: RunInstructionTemplateMetadata
  plan: RunInstructionTemplateMetadata
}

export interface RunInstructionTemplateBuiltIns extends RunInstructionTemplateDefaults {
  ci_auto_repair: RunInstructionTemplateMetadata
}

export interface RunInstructionTemplatePreviewRequest {
  issue_id: number
  task_mode: 'execute' | 'plan'
  user_prompt: string
  run_instruction_template: string
  require_changes?: boolean
}

export interface RunInstructionTemplatePreview {
  rendered_prompt: string
  used_placeholders: string[]
  unused_known_placeholders: string[]
}

export async function getTasks(params?: {
  status?: string
  project_id?: number
  initiator_username?: string
}): Promise<Task[]> {
  const response = await api.get('/tasks', { params })
  return response.data
}

export async function getTasksPaginated(params: {
  page: number
  page_size?: number
  status?: string
  project_id?: string | number
  initiator?: string
  initiator_username?: string
  priority?: string
  has_mr?: boolean | string
  search?: string
  created_after?: string
  created_before?: string
  scheduled_after?: string
  scheduled_before?: string
  sort_by?: string
  sort_order?: string
}): Promise<PaginatedResponse<Task>> {
  const response = await api.get('/tasks', { params })
  return response.data
}

export async function getScheduledTasks(
  params?: { project_id?: number; hour_start?: string; my?: boolean }
): Promise<Task[]> {
  const response = await api.get('/tasks/scheduled', { params })
  return response.data
}

export async function getScheduledStats(
  params?: { project_id?: number; my?: boolean }
): Promise<ScheduledStatsResponse> {
  const response = await api.get('/stats/scheduled', { params })
  return response.data
}

export async function getSlotCapacity(scheduledAt: string): Promise<SlotCapacityInfo> {
  const response = await api.get('/tasks/slot-capacity', {
    params: { scheduled_at: scheduledAt }
  })
  return response.data
}

export async function getTask(id: number): Promise<Task> {
  const response = await api.get(`/tasks/${id}`)
  return response.data
}

export async function getTaskModelServiceSummary(id: number): Promise<TaskModelServiceSummary> {
  const response = await api.get(`/tasks/${id}/model-service-summary`)
  return response.data
}

export async function getTaskWorkerRuntimeSummary(id: number): Promise<TaskWorkerRuntimeSummary> {
  const response = await api.get(`/tasks/${id}/worker-runtime-summary`)
  return response.data
}

export async function getTaskLogs(id: number): Promise<TaskLog[]> {
  const response = await api.get(`/tasks/${id}/logs`)
  return response.data
}

export function streamTaskLogs(
  id: number,
  sinceId: number,
  onLog: (log: TaskLog) => void,
  onDone?: () => void,
  onUpdate?: (log: TaskLog) => void,
): EventSource {
  const url = `/api/tasks/${id}/log-stream?since_id=${sinceId}`
  const source = new EventSource(url)
  const openTime = Date.now()
  let firstBatch = true
  let totalBatches = 0
  let totalLogs = 0

  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.error) {
        console.error(`[streamTaskLogs] server error: ${data.error}`)
      }
    } catch (error) {
      console.warn('[streamTaskLogs] failed to parse SSE message', error)
    }
  }

  source.addEventListener('batch', (event) => {
    try {
      const logs = JSON.parse((event as MessageEvent).data) as TaskLog[]
      totalBatches += 1
      totalLogs += logs.length
      if (firstBatch) {
        firstBatch = false
        console.debug(
          `[streamTaskLogs] task=${id} first-batch count=${logs.length} ` +
          `time_to_first_ms=${Date.now() - openTime}`
        )
      } else if (totalBatches % 10 === 0) {
        console.debug(
          `[streamTaskLogs] task=${id} batch #${totalBatches} ` +
          `count=${logs.length} total=${totalLogs}`
        )
      }
      for (const log of logs) {
        onLog(log)
      }
    } catch (error) {
      console.warn('[streamTaskLogs] failed to parse SSE batch event', error)
    }
  })

  source.addEventListener('done', () => {
    console.debug(
      `[streamTaskLogs] task=${id} done batches=${totalBatches} ` +
      `total_logs=${totalLogs} elapsed_ms=${Date.now() - openTime}`
    )
    source.close()
    onDone?.()
  })

  source.addEventListener('update', (event) => {
    try {
      onUpdate?.(JSON.parse((event as MessageEvent).data) as TaskLog)
    } catch (error) {
      console.warn('[streamTaskLogs] failed to parse SSE update event', error)
    }
  })

  source.onerror = (error) => {
    console.warn('[streamTaskLogs] SSE connection error', error)
  }

  return source
}

export async function getTaskContainerLogs(
  id: number,
  source?: 'db' | 'auto',
  tailChars?: number,
): Promise<TaskContainerLogsResponse> {
  const params: { source?: 'db' | 'auto', tail_chars?: number } = {}
  if (source) params.source = source
  if (tailChars !== undefined) params.tail_chars = tailChars
  const response = await api.get(`/tasks/${id}/container-logs`, { params })
  return response.data
}

export async function getTaskArchive(id: number): Promise<TaskArchive> {
  const response = await api.get(`/tasks/${id}/archive`)
  return response.data
}

export async function downloadTaskArchive(id: number): Promise<Blob> {
  const response = await api.get(`/tasks/${id}/archive/download`, {
    responseType: 'blob'
  })
  return response.data
}

export async function getTaskPayload(
  taskId: number,
  payloadId: number
): Promise<TaskPayloadResponse> {
  const response = await api.get(`/tasks/${taskId}/payloads/${payloadId}`)
  return response.data
}

export async function getTaskStats(id: number): Promise<TaskStats> {
  const response = await api.get(`/tasks/${id}/stats`)
  return response.data
}

export async function cancelTask(id: number): Promise<void> {
  await api.post(`/tasks/${id}/cancel`)
}

export async function overrideTaskStatus(
  id: number,
  status: 'completed' | 'failed',
  reason?: string
): Promise<void> {
  await api.post(`/tasks/${id}/override-status`, { status, reason: reason || null })
}

export async function retryTask(id: number, scheduledDatetime?: string): Promise<Task> {
  const body = scheduledDatetime ? { scheduled_datetime: scheduledDatetime } : undefined
  const { data } = await api.post(`/tasks/${id}/retry`, body)
  return data
}

export async function executeTask(id: number): Promise<void> {
  await api.post(`/tasks/${id}/execute`)
}

export async function createTask(request: CreateTaskRequest): Promise<Task> {
  const response = await api.post('/tasks', request)
  return response.data
}

export async function getRunInstructionTemplateDefaults(): Promise<RunInstructionTemplateDefaults> {
  const response = await api.get('/tasks/run-instruction-template-defaults')
  return response.data
}

export async function previewRunInstructionTemplate(
  request: RunInstructionTemplatePreviewRequest
): Promise<RunInstructionTemplatePreview> {
  const response = await api.post('/tasks/render-run-instruction-template-preview', request)
  return response.data
}

export async function getRunInstructionTemplateBuiltIns(): Promise<RunInstructionTemplateBuiltIns> {
  const response = await api.get('/config/run-instruction-template-built-ins')
  return response.data
}

export async function rescheduleTask(
  taskId: number,
  request: RescheduleTaskRequest
): Promise<Task> {
  const response = await api.patch(`/tasks/${taskId}/schedule`, request)
  return response.data
}

export async function updateTask(
  taskId: number,
  request: UpdateTaskRequest
): Promise<Task> {
  const response = await api.patch(`/tasks/${taskId}`, request)
  return response.data
}
