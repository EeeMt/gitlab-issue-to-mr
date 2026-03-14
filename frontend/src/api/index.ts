import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

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

export interface Config {
  max_concurrency: number
  task_timeout: number
  scheduler_interval: number
  default_target_branch: string
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

export async function updateConfig(config: Partial<Config>): Promise<Config> {
  const response = await api.patch('/config', config)
  return response.data
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
