<template>
  <div class="space-y-6">
    <!-- 全局集群策略配置卡片 -->
    <FormSection title="多 ChatGPT2API 集群调度策略" density="roomy">
      <p class="text-xs text-muted-foreground mb-4">
        将多台设备部署的 ChatGPT2API 实例组织为分布式高可用集群。主节点（当前实例）可根据策略将请求分发给各个节点，有效打散出口 IP、降低单个节点的风控风险，并支持故障时自动故障转移（Failover）。
      </p>

      <div class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
          <label class="flex items-center gap-2 text-xs font-semibold cursor-pointer">
            <input
              type="checkbox"
              v-model="form.enabled"
              class="rounded border-border"
              :disabled="loading || saving"
            />
            <span class="text-sm">启用多节点集群分发</span>
          </label>

          <span
            class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
            :class="form.enabled ? 'bg-emerald-500/10 text-emerald-600' : 'bg-muted text-muted-foreground'"
          >
            <span class="h-2 w-2 rounded-full" :class="form.enabled ? 'bg-emerald-500 animate-pulse' : 'bg-stone-400'"></span>
            {{ form.enabled ? '集群分发已启用' : '集群分发未启用 (仅本地)' }}
          </span>
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label class="block text-xs sm:col-span-2">
            <span class="ui-field-label">集群调度分发策略</span>
            <select
              v-model="form.strategy"
              class="ui-select-sm mt-1 w-full"
              :disabled="loading || saving || !form.enabled"
            >
              <option value="local_first">本地优先，远程备用 (推荐：本地有号先用本地，本地无号/冷却时自动转发至远程节点)</option>
              <option value="round_robin">轮询调度 (在本地与各远程节点之间按权重轮流分发)</option>
              <option value="random">随机负载均衡 (按各节点权重比例随机分配请求)</option>
              <option value="priority_order">按优先级主备 (按优先级数字 1 > 2 > 3 顺序调用，故障自动尝试下一级)</option>
              <option value="remote_only">仅远程集群 (不消耗本地账号，所有请求全部转发至远程节点)</option>
            </select>
          </label>

          <label class="block text-xs" v-if="form.strategy !== 'remote_only'">
            <span class="ui-field-label">本地节点调度权重 (默认 1)</span>
            <Input
              v-model.number="form.local_weight"
              type="number"
              min="0"
              step="1"
              block
              :disabled="loading || saving || !form.enabled"
            />
          </label>

          <label class="block text-xs" v-if="form.strategy === 'priority_order'">
            <span class="ui-field-label">本地节点优先级 (数字越小越优先)</span>
            <Input
              v-model.number="form.local_priority"
              type="number"
              min="1"
              step="1"
              block
              :disabled="loading || saving || !form.enabled"
            />
          </label>

          <label class="block text-xs">
            <span class="ui-field-label">集群请求超时限制 (秒)</span>
            <Input
              v-model.number="form.timeout_seconds"
              type="number"
              min="10"
              max="600"
              step="10"
              block
              :disabled="loading || saving || !form.enabled"
            />
          </label>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 pt-2">
          <label class="flex items-center gap-2 text-xs cursor-pointer">
            <input
              type="checkbox"
              v-model="form.retry_on_failure"
              class="rounded border-border"
              :disabled="loading || saving || !form.enabled"
            />
            <span>开启故障自动转移 (当选中节点出现网络超时或 5xx 异常时自动尝试下一个候选节点)</span>
          </label>

          <Button
            size="sm"
            variant="primary"
            :disabled="loading || saving"
            @click="handleSaveConfig"
          >
            {{ saving ? '正在保存...' : '保存集群策略' }}
          </Button>
        </div>
      </div>
    </FormSection>

    <!-- 集群节点列表卡片 -->
    <FormSection title="远程 ChatGPT2API 节点站点" density="roomy">
      <div class="flex items-center justify-between mb-3">
        <span class="text-xs text-muted-foreground">
          共 {{ nodes.length }} 个节点 ({{ onlineNodesCount }} 在线，{{ enabledNodesCount }} 启用)
        </span>
        <Button
          size="xs"
          variant="primary"
          @click="openAddNodeModal"
        >
          + 添加集群节点
        </Button>
      </div>

      <!-- 节点列表为空 -->
      <StateBlock v-if="!loading && nodes.length === 0" tag="p" compact dashed>
        暂无远程集群节点，点击右上角“+ 添加集群节点”配置其他设备的 ChatGPT2API 地址。
      </StateBlock>

      <!-- 节点列表卡片流 -->
      <div v-else class="space-y-3">
        <div
          v-for="node in nodes"
          :key="node.id"
          class="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div class="space-y-1 min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-sm text-foreground truncate">{{ node.name }}</span>
              <StateBadge
                :tone="node.status === 'online' ? 'success' : (node.status === 'offline' ? 'danger' : 'neutral')"
                density="compact"
              >
                {{ node.status === 'online' ? `在线 (${node.latency_ms}ms)` : (node.status === 'offline' ? '离线 / 异常' : '未检测') }}
              </StateBadge>
              <span v-if="!node.enabled" class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">已停用</span>
            </div>

            <div class="flex flex-wrap items-center gap-3 text-xs text-muted-foreground font-mono">
              <span class="truncate">{{ node.url }}</span>
              <span>权重: {{ node.weight }}</span>
              <span>优先级: {{ node.priority }}</span>
              <span v-if="node.last_checked_at" class="text-[11px]">检测于 {{ node.last_checked_at }}</span>
            </div>

            <p v-if="node.last_error" class="text-xs text-rose-500 font-mono">
              错误: {{ node.last_error }}
            </p>
          </div>

          <!-- 操作按钮组 -->
          <div class="flex flex-wrap items-center gap-2 shrink-0">
            <Button
              size="xs"
              variant="outline"
              :disabled="testingNodeId === node.id"
              @click="handleTestNode(node)"
            >
              {{ testingNodeId === node.id ? '检测中...' : '测试连通性' }}
            </Button>
            <Button
              size="xs"
              variant="outline"
              @click="handleToggleNode(node)"
            >
              {{ node.enabled ? '停用' : '启用' }}
            </Button>
            <Button
              size="xs"
              variant="outline"
              @click="openEditNodeModal(node)"
            >
              编辑
            </Button>
            <Button
              size="xs"
              variant="ghost"
              root-class="text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30"
              @click="handleDeleteNode(node)"
            >
              删除
            </Button>
          </div>
        </div>
      </div>
    </FormSection>

    <!-- 添加 / 编辑节点弹窗 -->
    <ModalShell :open="showNodeModal" @close="closeNodeModal">
      <div class="w-full max-w-lg rounded-2xl bg-card border border-border shadow-xl overflow-hidden">
        <ModalHeader
          :title="editingNodeId ? '编辑集群节点' : '添加集群节点'"
          compact
          @close="closeNodeModal"
        />
        <ModalBody class="space-y-4 p-5">
          <label class="block text-xs">
            <span class="ui-field-label">节点名称</span>
            <Input
              v-model.trim="nodeForm.name"
              block
              placeholder="例如：搬瓦工节点 1、备用服务器"
            />
          </label>

          <label class="block text-xs">
            <span class="ui-field-label">站点基础 URL (API Base URL)</span>
            <Input
              v-model.trim="nodeForm.url"
              block
              root-class="font-mono text-xs"
              placeholder="例如：http://192.168.1.100:3005 或 https://api2.example.com"
            />
          </label>

          <label class="block text-xs">
            <div class="flex items-center justify-between">
              <span class="ui-field-label">API 访问密钥 (API Key / Authorization)</span>
              <button
                type="button"
                class="text-[11px] text-muted-foreground hover:text-foreground"
                @click="showNodeKey = !showNodeKey"
              >
                {{ showNodeKey ? '隐藏' : '显示' }}
              </button>
            </div>
            <div class="mt-1">
              <Input
                v-model.trim="nodeForm.api_key"
                :type="showNodeKey ? 'text' : 'password'"
                block
                root-class="font-mono text-xs"
                placeholder="目标 ChatGPT2API 实例配置的 CHATGPT2API_AUTH_KEY"
              />
            </div>
          </label>

          <div class="grid grid-cols-2 gap-3">
            <label class="block text-xs">
              <span class="ui-field-label">调度权重 (默认 1)</span>
              <Input
                v-model.number="nodeForm.weight"
                type="number"
                min="1"
                step="1"
                block
              />
            </label>

            <label class="block text-xs">
              <span class="ui-field-label">调度优先级 (1 最优先)</span>
              <Input
                v-model.number="nodeForm.priority"
                type="number"
                min="1"
                step="1"
                block
              />
            </label>
          </div>

          <div class="flex items-center justify-between border-t border-border pt-3">
            <Button
              size="xs"
              variant="outline"
              :disabled="rawTesting || !nodeForm.url"
              @click="handleTestRawUrl"
            >
              {{ rawTesting ? '连通性测试中...' : '测试连通性' }}
            </Button>
            <span v-if="rawTestMsg" class="text-xs font-mono" :class="rawTestSuccess ? 'text-emerald-600' : 'text-rose-500'">
              {{ rawTestMsg }}
            </span>
          </div>
        </ModalBody>
        <ModalFooter class="flex justify-end gap-2 px-5 py-3 border-t border-border bg-muted/20">
          <Button size="sm" variant="outline" @click="closeNodeModal">取消</Button>
          <Button
            size="sm"
            variant="primary"
            :disabled="savingNode || !nodeForm.url"
            @click="handleSaveNode"
          >
            {{ savingNode ? '保存中...' : '保存节点' }}
          </Button>
        </ModalFooter>
      </div>
    </ModalShell>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Button, Input } from 'nanocat-ui'
import FormSection from '@/components/ai/FormSection.vue'
import StateBadge from '@/components/ai/StateBadge.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import { useToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { clusterApi, type ClusterConfig, type ClusterNode } from '@/api/cluster'

const toast = useToast()
const confirmDialog = useConfirmDialog()

const loading = ref(false)
const saving = ref(false)
const testingNodeId = ref('')

const form = ref<ClusterConfig>({
  enabled: false,
  strategy: 'local_first',
  local_weight: 1,
  local_priority: 1,
  retry_on_failure: true,
  timeout_seconds: 180,
  nodes: [],
})

const nodes = computed(() => form.value.nodes || [])
const onlineNodesCount = computed(() => nodes.value.filter((n) => n.status === 'online').length)
const enabledNodesCount = computed(() => nodes.value.filter((n) => n.enabled).length)

// 节点弹窗状态
const showNodeModal = ref(false)
const editingNodeId = ref('')
const savingNode = ref(false)
const showNodeKey = ref(false)
const rawTesting = ref(false)
const rawTestMsg = ref('')
const rawTestSuccess = ref(false)

const nodeForm = ref<Partial<ClusterNode>>({
  name: '',
  url: '',
  api_key: '',
  weight: 1,
  priority: 1,
  enabled: true,
})

async function loadData() {
  loading.value = true
  try {
    const res = await clusterApi.fetchConfig()
    if (res.cluster) {
      form.value = res.cluster
    }
  } catch (error: any) {
    toast.error(`加载集群配置失败: ${error?.message || error}`)
  } finally {
    loading.value = false
  }
}

async function handleSaveConfig() {
  saving.value = true
  try {
    const res = await clusterApi.updateConfig({
      enabled: form.value.enabled,
      strategy: form.value.strategy,
      local_weight: form.value.local_weight,
      local_priority: form.value.local_priority,
      retry_on_failure: form.value.retry_on_failure,
      timeout_seconds: form.value.timeout_seconds,
    })
    if (res.cluster) {
      form.value = res.cluster
    }
    toast.success('集群分发策略已保存')
  } catch (error: any) {
    toast.error(`保存失败: ${error?.message || error}`)
  } finally {
    saving.value = false
  }
}

function openAddNodeModal() {
  editingNodeId.value = ''
  nodeForm.value = {
    name: `节点 ${nodes.value.length + 1}`,
    url: '',
    api_key: '',
    weight: 1,
    priority: 1,
    enabled: true,
  }
  rawTestMsg.value = ''
  showNodeModal.value = true
}

function openEditNodeModal(node: ClusterNode) {
  editingNodeId.value = node.id
  nodeForm.value = { ...node }
  rawTestMsg.value = ''
  showNodeModal.value = true
}

function closeNodeModal() {
  if (savingNode.value) return
  showNodeModal.value = false
}

async function handleTestRawUrl() {
  if (!nodeForm.value.url) return
  rawTesting.value = true
  rawTestMsg.value = ''
  try {
    const res = await clusterApi.testRawUrl(nodeForm.value.url, nodeForm.value.api_key || '')
    const r = res.result
    rawTestSuccess.value = r.ok
    rawTestMsg.value = r.ok ? `连接成功！延迟 ${r.latency_ms}ms (模型数: ${r.models_count})` : `连接失败: ${r.error}`
  } catch (err: any) {
    rawTestSuccess.value = false
    rawTestMsg.value = `测试异常: ${err?.message || err}`
  } finally {
    rawTesting.value = false
  }
}

async function handleSaveNode() {
  if (!nodeForm.value.url) {
    toast.warning('请输入站点基础 URL')
    return
  }
  savingNode.value = true
  try {
    if (editingNodeId.value) {
      const res = await clusterApi.updateNode(editingNodeId.value, nodeForm.value)
      form.value = res.cluster
      toast.success('集群节点已更新')
    } else {
      const res = await clusterApi.addNode(nodeForm.value)
      form.value = res.cluster
      toast.success('已添加新集群节点')
    }
    showNodeModal.value = false
  } catch (error: any) {
    toast.error(`保存节点失败: ${error?.message || error}`)
  } finally {
    savingNode.value = false
  }
}

async function handleToggleNode(node: ClusterNode) {
  try {
    const res = await clusterApi.updateNode(node.id, { enabled: !node.enabled })
    form.value = res.cluster
    toast.success(node.enabled ? '节点已停用' : '节点已启用')
  } catch (err: any) {
    toast.error(`更新节点状态失败: ${err?.message || err}`)
  }
}

async function handleTestNode(node: ClusterNode) {
  testingNodeId.value = node.id
  try {
    const res = await clusterApi.testNode(node.id)
    form.value = res.cluster
    const r = res.result
    if (r.ok) {
      toast.success(`节点 [${node.name}] 连接成功，延迟 ${r.latency_ms}ms`)
    } else {
      toast.error(`节点 [${node.name}] 离线: ${r.error}`)
    }
  } catch (err: any) {
    toast.error(`测试失败: ${err?.message || err}`)
  } finally {
    testingNodeId.value = ''
  }
}

async function handleDeleteNode(node: ClusterNode) {
  const confirmed = await confirmDialog.confirm({
    title: '确认删除节点',
    message: `确定要删除集群节点 [${node.name}] (${node.url}) 吗？`,
    confirmText: '确认删除',
    cancelText: '取消',
  })
  if (!confirmed) return
  try {
    const res = await clusterApi.deleteNode(node.id)
    form.value = res.cluster
    toast.success('节点已删除')
  } catch (err: any) {
    toast.error(`删除节点失败: ${err?.message || err}`)
  }
}

onMounted(() => {
  void loadData()
})
</script>
