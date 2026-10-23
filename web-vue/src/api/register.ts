import apiClient, { getAuthToken } from './client'

export interface RegisterStats {
  success: number
  fail: number
  done: number
  running: number
  threads: number
  elapsed_seconds?: number
  avg_seconds?: number
  consecutive_failures?: number
  scheduler_restarts?: number
  pause_reason?: string | null
  current_quota?: number
  current_available?: number
  retry_at?: string | null
  periodic_round?: number
  next_round_at?: string | null
}

export interface RegisterLogItem {
  time: string
  level: string
  text: string
}

export interface MailProviderConfig {
  enable: boolean
  type: string
  api_base?: string
  admin_email?: string
  admin_password?: string
  subdomain?: string[]
  email_prefix?: string
  api_key?: string
  domain?: string[]
  ddg_token?: string
  cf_inbox_jwt?: string
  cf_domain?: string[]
  subdomain_levels?: string[]
  random_subdomain_depth?: number
  append_random_suffix?: boolean
  fixed_address?: string
  mailboxes?: string
  mode?: string
  imap_host?: string
  message_limit?: number
}

export interface MailSettings {
  request_timeout: number
  wait_timeout: number
  wait_interval: number
  api_use_register_proxy: boolean
  providers: MailProviderConfig[]
}

export interface RoxyConfig {
  api_base: string
  api_token: string
  workspace_id: string
  project_id: string
  profile_id?: string
  open_headless: boolean
  create_use_proxy_pool: boolean
  proxy_pool: string
  activate_account: boolean
  otp_wait_seconds: number
  ignore_proxy_check?: boolean
}

export interface RegisterConfig {
  mail: MailSettings
  proxy: string
  total: number
  threads: number
  mode: 'total' | 'quota' | 'available' | 'periodic' | string
  target_quota: number
  target_available: number
  check_interval: number
  periodic_interval_hours?: number
  periodic_count?: number
  schedule_enabled: boolean
  schedule_start: string
  schedule_end: string
  enabled: boolean
  roxy?: RoxyConfig
  stats?: RegisterStats
  logs?: RegisterLogItem[]
}

export async function fetchRoxyRegisterConfig(): Promise<{ register: RegisterConfig }> {
  return apiClient.get('/api/register/roxy')
}

export async function saveRoxyRegisterConfig(config: Partial<RegisterConfig>): Promise<{ register: RegisterConfig }> {
  return apiClient.post('/api/register/roxy', config)
}

export async function startRoxyRegister(config?: Partial<RegisterConfig>): Promise<{ register: RegisterConfig }> {
  return apiClient.post('/api/register/roxy/start', config || {})
}

export async function stopRoxyRegister(): Promise<{ register: RegisterConfig }> {
  return apiClient.post('/api/register/roxy/stop')
}

export async function resetRoxyRegister(): Promise<{ register: RegisterConfig }> {
  return apiClient.post('/api/register/roxy/reset')
}

export async function fetchRoxyWorkspaces(): Promise<{ ok: boolean; items: Array<{ id: string; name: string; projectId?: string; projectName?: string; label?: string }> }> {
  return apiClient.get('/api/register/roxy/workspaces')
}

export async function fetchSharedRegisterConfig(): Promise<{ register: RegisterConfig }> {
  return apiClient.get('/api/register')
}

export async function saveSharedRegisterConfig(config: Partial<RegisterConfig>): Promise<{ register: RegisterConfig }> {
  return apiClient.post('/api/register', config)
}

export function subscribeRoxyRegisterEvents(
  onData: (config: RegisterConfig) => void,
  onError?: (err: Event) => void,
): () => void {
  const token = getAuthToken()
  const baseUrl = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
  const url = `${baseUrl}/api/register/roxy/events?token=${encodeURIComponent(token)}`
  const es = new EventSource(url)

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as RegisterConfig
      onData(data)
    } catch {
      // ignore JSON parse error on heartbeat
    }
  }

  if (onError) {
    es.onerror = onError
  }

  return () => {
    es.close()
  }
}
