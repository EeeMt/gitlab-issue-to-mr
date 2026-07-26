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

export interface ListFilterOptions {
  initiators: InitiatorFilterOption[]
}

export function snapshotInitiatorValue(username: string): string {
  return `snapshot:${username}`
}

export async function getIssueFilterOptions(): Promise<ListFilterOptions> {
  const response = await api.get('/issues/filter-options')
  return response.data
}

export async function getTaskFilterOptions(): Promise<ListFilterOptions> {
  const response = await api.get('/tasks/filter-options')
  return response.data
}
