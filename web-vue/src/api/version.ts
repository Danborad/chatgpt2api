import apiClient from './client'
import type {
  UpdateTaskEventResponse,
  UpdateTaskResponse,
  VersionCheckResponse,
  VersionInfoResponse,
} from '@/types/api'

function expectRecord(value: unknown, path: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Version update response contract mismatch at ${path}`)
  }
  return value as Record<string, unknown>
}

function expectString(value: unknown, path: string): string {
  if (typeof value !== 'string') {
    throw new Error(`Version update response contract mismatch at ${path}`)
  }
  return value
}

function expectBoolean(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`Version update response contract mismatch at ${path}`)
  }
  return value
}

function expectNumber(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Version update response contract mismatch at ${path}`)
  }
  return value
}

function expectArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`Version update response contract mismatch at ${path}`)
  }
  return value
}

function expectEnum<T extends string>(value: unknown, path: string, allowed: readonly T[]): T {
  const result = expectString(value, path)
  if (!allowed.includes(result as T)) {
    throw new Error(`Version update response contract mismatch at ${path}`)
  }
  return result as T
}

const updateTones = ['info', 'success', 'warning', 'danger'] as const
const updateStates = ['idle', 'queued', 'running', 'succeeded', 'failed'] as const
const updateStages = [
  'idle',
  'queued',
  'checking',
  'downloading',
  'verifying',
  'installing',
  'syncing',
  'restarting',
  'completed',
  'failed',
] as const

export function parseVersionCheckResponse(value: unknown): VersionCheckResponse {
  const root = expectRecord(value, 'response')
  return {
    current_tag: expectString(root.current_tag, 'response.current_tag'),
    latest_tag: expectString(root.latest_tag, 'response.latest_tag'),
    update_available: expectBoolean(root.update_available, 'response.update_available'),
    release_url: expectString(root.release_url, 'response.release_url'),
    status_label: expectString(root.status_label, 'response.status_label'),
    status_message: expectString(root.status_message, 'response.status_message'),
    tone: expectEnum(root.tone, 'response.tone', ['success', 'muted', 'warning'] as const),
    changelog: expectString(root.changelog, 'response.changelog'),
    can_update: expectBoolean(root.can_update, 'response.can_update'),
  }
}

function parseUpdateTaskEvent(value: unknown, index: number): UpdateTaskEventResponse {
  const path = `response.events[${index}]`
  const event = expectRecord(value, path)
  return {
    id: expectString(event.id, `${path}.id`),
    timestamp: expectString(event.timestamp, `${path}.timestamp`),
    label: expectString(event.label, `${path}.label`),
    message: expectString(event.message, `${path}.message`),
    tone: expectEnum(event.tone, `${path}.tone`, updateTones),
  }
}

export function parseUpdateTaskResponse(value: unknown): UpdateTaskResponse {
  const root = expectRecord(value, 'response')
  return {
    task_id: expectString(root.task_id, 'response.task_id'),
    state: expectEnum(root.state, 'response.state', updateStates),
    stage: expectEnum(root.stage, 'response.stage', updateStages),
    current: expectNumber(root.current, 'response.current'),
    total: expectNumber(root.total, 'response.total'),
    status_label: expectString(root.status_label, 'response.status_label'),
    message: expectString(root.message, 'response.message'),
    tone: expectEnum(root.tone, 'response.tone', updateTones),
    busy: expectBoolean(root.busy, 'response.busy'),
    current_tag: expectString(root.current_tag, 'response.current_tag'),
    latest_tag: expectString(root.latest_tag, 'response.latest_tag'),
    error: expectString(root.error, 'response.error'),
    updated_at: expectString(root.updated_at, 'response.updated_at'),
    events: expectArray(root.events, 'response.events').map(parseUpdateTaskEvent),
  }
}

function toVersionInfo(payload: { version?: string }): VersionInfoResponse {
  const version = String(payload.version || '').trim()
  return {
    version,
    tag: version.startsWith('v') ? version : `v${version}`,
    commit: '',
  }
}

export const versionApi = {
  async current() {
    const payload = await apiClient.get<never, { version: string }>('/version')
    return toVersionInfo(payload)
  },

  async check(force = false): Promise<VersionCheckResponse> {
    const payload = await apiClient.get<never, unknown>('/api/system/update-status', {
      params: force ? { force: true } : undefined,
    })
    return parseVersionCheckResponse(payload)
  },

  async updateTask(): Promise<UpdateTaskResponse> {
    const payload = await apiClient.get<never, unknown>('/api/system/update-task')
    return parseUpdateTaskResponse(payload)
  },

  async startUpdate(): Promise<UpdateTaskResponse> {
    const payload = await apiClient.post<never, unknown>('/api/system/update')
    return parseUpdateTaskResponse(payload)
  },
}
