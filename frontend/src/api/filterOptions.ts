import { api } from './client'

export type InitiatorFilterKind = 'user' | 'legacy' | 'unknown'

export interface InitiatorFilterOption {
  value: string
  kind: InitiatorFilterKind
  user_id: number | null
  username: string | null
  display_name: string | null
  count: number
}

export interface SimpleFilterOption {
  value: string
  label: string
  count: number
}

export interface ListFilterOptions {
  initiators: InitiatorFilterOption[]
}

export interface TaskFilterOptions extends ListFilterOptions {
  harnesses: SimpleFilterOption[]
}

export interface IssueFilterOptions extends ListFilterOptions {
  worker_kits: SimpleFilterOption[]
}

export function snapshotInitiatorValue(username: string): string {
  return `snapshot:${username}`
}

export async function getIssueFilterOptions(): Promise<IssueFilterOptions> {
  const response = await api.get('/issues/filter-options')
  return response.data
}

export async function getTaskFilterOptions(): Promise<TaskFilterOptions> {
  const response = await api.get('/tasks/filter-options')
  return response.data
}
