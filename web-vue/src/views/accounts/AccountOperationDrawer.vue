<template>
  <OperationProgressDrawer
    :open="open"
    :minimized="minimized"
    :title="title || '账号任务记录'"
    :subtitle="`${processed} / ${total} · ${percent}%`"
    :total="total"
    :current="processed"
    :percent="percent"
    :status-label="statusText"
    :error="progress?.error || ''"
    :busy="!canClose"
    :tone="progress?.tone || (progress?.error ? 'danger' : 'info')"
    :events="timelineEvents"
    :summary-items="progress?.summary_items || []"
    :can-cancel="canStop"
    :cancel-disabled="stopRequested"
    :cancel-label="stopRequested ? '停止中...' : '停止'"
    :close-disabled="!canClose"
    :can-retry="canRetry"
    :retry-label="retryLabel"
    :retry-prompt="retryPrompt"
    :can-copy-failed="canCopyFailed"
    copy-failed-label="复制失败卡密"
    @update:minimized="emit('update:minimized', $event)"
    @cancel="emit('stop')"
    @close="emit('close')"
    @retry="emit('retry')"
    @copy-failed="emit('copyFailed')"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AccountOperationProgress } from '@/api/accounts'
import OperationProgressDrawer from '@/components/ai/OperationProgressDrawer.vue'
import type { OperationTimelineEvent } from '@/composables/useOperationProgressRuntime'
import type { AccountOperationTimelineEvent } from './accountBulkProgressRuntime'

const props = defineProps<{
  open: boolean
  minimized?: boolean
  title: string
  statusText: string
  progress: AccountOperationProgress | null
  percent: number
  events: AccountOperationTimelineEvent[]
  canStop: boolean
  stopRequested: boolean
  canClose: boolean
}>()

const emit = defineEmits<{
  close: []
  stop: []
  retry: []
  copyFailed: []
  'update:minimized': [value: boolean]
}>()

const processed = computed(() => Math.max(0, Number(props.progress?.processed || 0)))
const total = computed(() => Math.max(0, Number(props.progress?.total || 0)))
const failedCount = computed(() => (props.progress?.failed_items ? props.progress.failed_items.length : 0))
const canRetry = computed(() => failedCount.value > 0)
const retryLabel = computed(() => `重试失败账号 (${failedCount.value})`)
const retryPrompt = computed(() => `检测到 ${failedCount.value} 个账号登录授权失败`)
const canCopyFailed = computed(() => failedCount.value > 0)

const timelineEvents = computed<OperationTimelineEvent[]>(() => props.events.map((event) => ({
  key: event.key,
  timestamp: event.timestamp,
  label: event.account_label || event.account_id || '任务',
  message: event.message,
  tone: event.tone,
})))
</script>
