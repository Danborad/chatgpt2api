import {
  DASHBOARD_TIME_RANGE_OPTIONS,
  DEFAULT_DASHBOARD_TIME_RANGE,
  type DashboardTimeRange,
} from '@/lib/timeRanges'

export const DASHBOARD_REFRESH_INTERVAL_STORAGE_KEY = 'chatgpt2api_dashboard_refresh_interval_secs'
export const DASHBOARD_DEFAULT_TIME_RANGE_STORAGE_KEY = 'chatgpt2api_dashboard_default_time_range'
export const DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS = 10
export const MIN_DASHBOARD_REFRESH_INTERVAL_SECONDS = 5
export const MAX_DASHBOARD_REFRESH_INTERVAL_SECONDS = 300

export function normalizeDashboardRefreshIntervalSeconds(value: unknown) {
  const rawValue = String(value ?? '').trim()
  if (!rawValue) return DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS
  const seconds = Math.round(Number(rawValue))
  if (!Number.isFinite(seconds)) return DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS
  return Math.min(
    MAX_DASHBOARD_REFRESH_INTERVAL_SECONDS,
    Math.max(MIN_DASHBOARD_REFRESH_INTERVAL_SECONDS, seconds),
  )
}

export function readDashboardRefreshIntervalSeconds() {
  if (typeof window === 'undefined') return DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS
  try {
    return normalizeDashboardRefreshIntervalSeconds(
      window.localStorage.getItem(DASHBOARD_REFRESH_INTERVAL_STORAGE_KEY),
    )
  } catch {
    return DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS
  }
}

export function writeDashboardRefreshIntervalSeconds(value: unknown) {
  const seconds = normalizeDashboardRefreshIntervalSeconds(value)
  try {
    window.localStorage.setItem(DASHBOARD_REFRESH_INTERVAL_STORAGE_KEY, String(seconds))
  } catch {
    // Ignore storage errors; the in-memory value remains usable.
  }
  return seconds
}

export function normalizeDashboardDefaultTimeRange(value: unknown): DashboardTimeRange {
  const normalized = String(value || '').trim() as DashboardTimeRange
  return DASHBOARD_TIME_RANGE_OPTIONS.some((option) => option.value === normalized)
    ? normalized
    : DEFAULT_DASHBOARD_TIME_RANGE
}

export function readDashboardDefaultTimeRange(): DashboardTimeRange {
  if (typeof window === 'undefined') return DEFAULT_DASHBOARD_TIME_RANGE
  try {
    return normalizeDashboardDefaultTimeRange(
      window.localStorage.getItem(DASHBOARD_DEFAULT_TIME_RANGE_STORAGE_KEY),
    )
  } catch {
    return DEFAULT_DASHBOARD_TIME_RANGE
  }
}

export function writeDashboardDefaultTimeRange(value: unknown): DashboardTimeRange {
  const range = normalizeDashboardDefaultTimeRange(value)
  try {
    window.localStorage.setItem(DASHBOARD_DEFAULT_TIME_RANGE_STORAGE_KEY, range)
  } catch {
    // Ignore storage errors; the in-memory value remains usable.
  }
  return range
}
