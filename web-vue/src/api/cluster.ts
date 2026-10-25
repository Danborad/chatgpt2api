import apiClient from './client'

export interface ClusterNode {
  id: string
  name: string
  url: string
  api_key: string
  weight: number
  priority: number
  enabled: boolean
  status: 'online' | 'offline' | 'unknown' | string
  latency_ms: number
  last_checked_at: string
  last_error: string
}

export interface ClusterConfig {
  enabled: boolean
  strategy: 'local_first' | 'round_robin' | 'random' | 'priority_order' | 'remote_only'
  local_weight: number
  local_priority: number
  retry_on_failure: boolean
  timeout_seconds: number
  nodes: ClusterNode[]
}

export interface NodeTestResult {
  ok: boolean
  status_code?: number
  latency_ms: number
  models_count?: number
  error?: string
}

export const clusterApi = {
  fetchConfig: () =>
    apiClient.get<never, { cluster: ClusterConfig }>('/api/cluster'),

  updateConfig: (data: Partial<ClusterConfig>) =>
    apiClient.post<Partial<ClusterConfig>, { cluster: ClusterConfig }>('/api/cluster', data),

  addNode: (node: Partial<ClusterNode>) =>
    apiClient.post<Partial<ClusterNode>, { node: ClusterNode; cluster: ClusterConfig }>('/api/cluster/nodes', node),

  updateNode: (id: string, updates: Partial<ClusterNode>) =>
    apiClient.put<Partial<ClusterNode>, { node: ClusterNode; cluster: ClusterConfig }>(
      `/api/cluster/nodes/${encodeURIComponent(id)}`,
      updates,
    ),

  deleteNode: (id: string) =>
    apiClient.delete<never, { success: boolean; cluster: ClusterConfig }>(
      `/api/cluster/nodes/${encodeURIComponent(id)}`,
    ),

  testNode: (id: string) =>
    apiClient.post<never, { result: NodeTestResult; cluster: ClusterConfig }>(
      `/api/cluster/nodes/${encodeURIComponent(id)}/test`,
    ),

  testRawUrl: (url: string, apiKey = '') =>
    apiClient.post<{ url: string; api_key: string }, { result: NodeTestResult }>(
      '/api/cluster/test-url',
      { url, api_key: apiKey },
    ),
}
