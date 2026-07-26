import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }))

vi.mock('./client', () => ({
  api: { get: mockGet },
}))

import {
  getIssueFilterOptions,
  getTaskFilterOptions,
  snapshotInitiatorValue,
} from './filterOptions'

describe('list filter options API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: { initiators: [] } })
  })

  it('loads issue initiator facets from the issue-scoped endpoint', async () => {
    await expect(getIssueFilterOptions()).resolves.toEqual({ initiators: [] })
    expect(mockGet).toHaveBeenCalledWith('/issues/filter-options')
  })

  it('loads task initiator facets from the task-scoped endpoint', async () => {
    await expect(getTaskFilterOptions()).resolves.toEqual({ initiators: [] })
    expect(mockGet).toHaveBeenCalledWith('/tasks/filter-options')
  })

  it('encodes legacy snapshot usernames so reserved values remain unambiguous', () => {
    expect(snapshotInitiatorValue('unknown')).toBe('snapshot:unknown')
  })
})
