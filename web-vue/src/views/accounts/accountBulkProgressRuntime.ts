import { computed, nextTick, ref } from 'vue'

import apiClient from '@/api/client'
import type {
  AccountOperationEvent,
  AccountOperationProgress,
} from '@/api/accounts'

export type AccountBulkProgressKind = 'sync' | 'credentials' | 'mutation' | 'import'

export interface AccountOperationTimelineEvent extends AccountOperationEvent {
  key: string
}

type AccountBulkProgressPatch = Partial<AccountOperationProgress> & {
  total: number
  processed?: number
  progress_id?: string
}

const ACCOUNT_OPERATION_EVENT_LIMIT = 500
const BULK_PROGRESS_STORAGE_KEY = 'chatgpt2api:bulk_progress_session'

interface BulkProgressSession {
  progressId?: string
  title: string
  total: number
  kind: AccountBulkProgressKind
  minimized: boolean
  startedAt: number
  updatedAt: number
}

function cleanText(value: unknown) {
  return String(value || '').trim()
}

export function useAccountBulkProgressRuntime() {
  const batchBusy = ref(false)
  const showRefreshProgress = ref(false)
  const refreshProgressTitle = ref('')
  const refreshProgress = ref<AccountOperationProgress | null>(null)
  const refreshProgressKind = ref<AccountBulkProgressKind>('sync')
  const bulkStopRequested = ref(false)
  const bulkStopEnabled = ref(false)
  const operationEvents = ref<AccountOperationTimelineEvent[]>([])
  const backendEventKeys = new Set<string>()
  const minimized = ref(false)
  const activeProgressId = ref('')
  let pollTimer: number | null = null

  function saveSession() {
    if (typeof window === 'undefined') return
    try {
      if (!showRefreshProgress.value) {
        window.localStorage.removeItem(BULK_PROGRESS_STORAGE_KEY)
        return
      }
      const session: BulkProgressSession = {
        progressId: activeProgressId.value || undefined,
        title: refreshProgressTitle.value,
        total: Math.max(0, Number(refreshProgress.value?.total || 0)),
        kind: refreshProgressKind.value,
        minimized: minimized.value,
        startedAt: Date.now(),
        updatedAt: Date.now(),
      }
      window.localStorage.setItem(BULK_PROGRESS_STORAGE_KEY, JSON.stringify(session))
    } catch {
      // ignore storage error
    }
  }

  function clearSession() {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.removeItem(BULK_PROGRESS_STORAGE_KEY)
    } catch {
      // ignore
    }
  }

  function setMinimized(val: boolean) {
    minimized.value = val
    saveSession()
  }

  function recordProgressId(id: string) {
    const cleanId = String(id || '').trim()
    if (!cleanId) return
    activeProgressId.value = cleanId
    saveSession()
  }

  function trimEvents() {
    if (operationEvents.value.length <= ACCOUNT_OPERATION_EVENT_LIMIT) return
    operationEvents.value = operationEvents.value.slice(-ACCOUNT_OPERATION_EVENT_LIMIT)
  }

  function mergeBackendEvents(events: AccountOperationEvent[] | undefined) {
    if (!Array.isArray(events) || events.length === 0) return
    const additions: AccountOperationTimelineEvent[] = []
    for (const [index, raw] of events.entries()) {
      if (!raw || typeof raw !== 'object') continue
      const message = cleanText(raw.message)
      if (!message) continue
      const sequence = Number.isFinite(Number(raw.sequence))
        ? Math.max(0, Number(raw.sequence))
        : index + 1
      const timestamp = cleanText(raw.timestamp)
      const key = [
        'backend',
        sequence,
        timestamp,
        cleanText(raw.action),
        cleanText(raw.account_id),
        message,
      ].join(':')
      if (backendEventKeys.has(key)) continue
      backendEventKeys.add(key)
      additions.push({
        key,
        sequence,
        timestamp,
        account_id: cleanText(raw.account_id),
        account_label: cleanText(raw.account_label),
        action: cleanText(raw.action),
        status: raw.status,
        tone: raw.tone,
        message,
      })
    }
    if (!additions.length) return
    operationEvents.value = [...operationEvents.value, ...additions]
    trimEvents()
  }

  const refreshProgressPercent = computed(() => {
    const progress = refreshProgress.value
    const total = Math.max(0, Number(progress?.total || 0))
    if (total <= 0) return 0
    return Math.min(100, Math.round((Math.max(0, Number(progress?.processed || 0)) / total) * 100))
  })

  const refreshProgressStatusText = computed(() => {
    const progress = refreshProgress.value
    if (bulkStopRequested.value) return '停止中'
    if (progress?.status_label) return progress.status_label
    if (progress?.error) return '失败'
    if (progress?.done) return '已完成'
    return progress?.stage_label || '处理中'
  })

  const canStopRefreshProgress = computed(() => (
    bulkStopEnabled.value
    && showRefreshProgress.value
    && batchBusy.value
    && !refreshProgress.value?.done
  ))

  const canCloseRefreshProgress = computed(() => (
    Boolean(refreshProgress.value?.done) || !batchBusy.value
  ))

  async function start(
    title: string,
    total: number,
    kind: AccountBulkProgressKind,
    options: { stoppable?: boolean } = {},
  ) {
    backendEventKeys.clear()
    operationEvents.value = []
    bulkStopRequested.value = false
    bulkStopEnabled.value = Boolean(options.stoppable)
    batchBusy.value = true
    showRefreshProgress.value = true
    minimized.value = false
    activeProgressId.value = ''
    refreshProgressTitle.value = title
    refreshProgressKind.value = kind
    refreshProgress.value = {
      total,
      processed: 0,
      done: false,
      error: null,
      total_quota: kind === 'sync' ? 0 : undefined,
      result: null,
    }
    saveSession()
    await nextTick()
    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') return
    await new Promise<void>((resolve) => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        window.clearTimeout(fallbackTimer)
        resolve()
      }
      const fallbackTimer = window.setTimeout(finish, 80)
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(finish)
      })
    })
  }

  function end() {
    batchBusy.value = false
  }

  function update(patch: AccountBulkProgressPatch) {
    mergeBackendEvents(patch.events)
    if (patch.progress_id) {
      activeProgressId.value = String(patch.progress_id).trim()
    }
    const current = refreshProgress.value || { total: patch.total, processed: 0, done: false }
    refreshProgress.value = {
      ...current,
      ...patch,
      done: patch.done === undefined ? current.done : Boolean(patch.done),
    }
    saveSession()
  }

  function finish(patch: AccountBulkProgressPatch) {
    mergeBackendEvents(patch.events)
    if (patch.progress_id) {
      activeProgressId.value = String(patch.progress_id).trim()
    }
    const progress: AccountOperationProgress = {
      ...(refreshProgress.value || { total: patch.total, processed: patch.processed || 0, done: false }),
      ...patch,
      done: true,
    }
    refreshProgress.value = progress
    saveSession()
  }

  function fail(total: number, processed: number, error: string) {
    const progress: AccountOperationProgress = {
      ...(refreshProgress.value || { total, processed, done: false }),
      total,
      processed,
      done: true,
      error,
    }
    refreshProgress.value = progress
    saveSession()
  }

  function requestStop() {
    if (!canStopRefreshProgress.value) return false
    bulkStopRequested.value = true
    return true
  }

  function close() {
    if (!refreshProgress.value?.done && batchBusy.value) return false
    if (pollTimer) {
      window.clearTimeout(pollTimer)
      pollTimer = null
    }
    showRefreshProgress.value = false
    activeProgressId.value = ''
    clearSession()
    return true
  }

  async function pollProgress(progressId: string, onFinished?: () => Promise<void> | void) {
    if (!progressId) return
    const runPoll = async () => {
      try {
        const res = await apiClient.get<never, AccountOperationProgress>(
          `/api/accounts/operations/${encodeURIComponent(progressId)}`,
        )
        update(res)
        if (res.done || res.error) {
          finish(res)
          end()
          void Promise.resolve(onFinished?.()).catch(() => {})
          return
        }
      } catch {
        // 网络短暂异常不中断，等待下一轮重试
      }
      if (showRefreshProgress.value && !refreshProgress.value?.done) {
        pollTimer = window.setTimeout(runPoll, 1000)
      }
    }
    await runPoll()
  }

  async function resumeSession(onFinished?: () => Promise<void> | void) {
    if (typeof window === 'undefined') return
    if (showRefreshProgress.value && batchBusy.value) return
    try {
      const raw = window.localStorage.getItem(BULK_PROGRESS_STORAGE_KEY)
      if (!raw) return
      const session: BulkProgressSession = JSON.parse(raw)
      if (!session || !session.title) return
      // 超过 12 小时的任务自动清理
      if (Date.now() - Number(session.updatedAt || 0) > 12 * 3600 * 1000) {
        clearSession()
        return
      }
      showRefreshProgress.value = true
      minimized.value = Boolean(session.minimized)
      refreshProgressTitle.value = session.title
      refreshProgressKind.value = session.kind || 'import'
      const total = Math.max(0, Number(session.total || 0))
      refreshProgress.value = {
        total,
        processed: 0,
        done: false,
        error: null,
        stage_label: '正在恢复后台任务状态...',
      }
      if (session.progressId) {
        activeProgressId.value = session.progressId
        batchBusy.value = true
        await pollProgress(session.progressId, onFinished)
      }
    } catch {
      // ignore
    }
  }

  return {
    batchBusy,
    showRefreshProgress,
    refreshProgressTitle,
    refreshProgress,
    refreshProgressKind,
    refreshProgressPercent,
    refreshProgressStatusText,
    canStopRefreshProgress,
    canCloseRefreshProgress,
    bulkStopRequested,
    bulkStopEnabled,
    operationEvents,
    minimized,
    setMinimized,
    recordProgressId,
    resumeSession,
    appendEvents: mergeBackendEvents,
    start,
    end,
    update,
    finish,
    fail,
    requestStop,
    close,
  }
}
