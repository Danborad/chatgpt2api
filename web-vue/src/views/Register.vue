<template>
  <div class="space-y-6">
    <PagePanel class="space-y-5">
      <PanelHeader title="Roxy 指纹注册机" align="start">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            使用本机 Roxy 指纹浏览器 + Selenium 自动化注册 ChatGPT 账号。注册成功后自动拦截授权换取官方 Platform OAuth <b>Refresh Token (RT)</b> 与 <b>Access Token (AT)</b>，彻底解决 10 天凭据过期失效问题。
          </p>
        </template>
        <template #actions>
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
              :class="registerConfig?.enabled ? 'bg-emerald-500/10 text-emerald-600' : 'bg-muted text-muted-foreground'"
            >
              <span class="h-2 w-2 rounded-full" :class="registerConfig?.enabled ? 'bg-emerald-500 animate-pulse' : 'bg-stone-400'"></span>
              {{ registerConfig?.enabled ? '运行中' : '已停止' }}
            </span>
            <Button
              v-if="!registerConfig?.enabled"
              size="sm"
              variant="primary"
              :disabled="loading || actionLoading"
              @click="handleStart"
            >
              启动 Roxy
            </Button>
            <Button
              v-else
              size="sm"
              variant="outline"
              root-class="text-rose-600 hover:bg-rose-50"
              :disabled="loading || actionLoading"
              @click="handleStop"
            >
              停止 Roxy
            </Button>
            <Button
              size="sm"
              variant="outline"
              :disabled="loading || actionLoading || registerConfig?.enabled"
              @click="handleReset"
            >
              重置统计
            </Button>
          </div>
        </template>
      </PanelHeader>

      <!-- 状态指标看板 -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <SurfaceBox density="compact" class="text-center">
          <p class="text-[11px] text-muted-foreground">成功 / 成功率</p>
          <p class="mt-1 text-lg font-semibold text-emerald-600">
            {{ stats.success }}
            <span class="text-xs font-normal text-muted-foreground">({{ successRate }}%)</span>
          </p>
        </SurfaceBox>

        <SurfaceBox density="compact" class="text-center">
          <p class="text-[11px] text-muted-foreground">失败</p>
          <p class="mt-1 text-lg font-semibold text-rose-600">{{ stats.fail }}</p>
        </SurfaceBox>

        <SurfaceBox density="compact" class="text-center">
          <p class="text-[11px] text-muted-foreground">完成总数</p>
          <p class="mt-1 text-lg font-semibold text-foreground">{{ stats.done }}</p>
        </SurfaceBox>

        <SurfaceBox density="compact" class="text-center">
          <p class="text-[11px] text-muted-foreground">运行 / 线程</p>
          <p class="mt-1 text-lg font-semibold text-foreground">{{ stats.running }} / {{ stats.threads || 1 }}</p>
        </SurfaceBox>

        <SurfaceBox density="compact" class="text-center">
          <p class="text-[11px] text-muted-foreground">累计运行</p>
          <p class="mt-1 text-lg font-semibold text-foreground">{{ stats.elapsed_seconds || 0 }}s</p>
        </SurfaceBox>

        <SurfaceBox density="compact" class="text-center">
          <p class="text-[11px] text-muted-foreground">平均单账号</p>
          <p class="mt-1 text-lg font-semibold text-foreground">{{ stats.avg_seconds || 0 }}s</p>
        </SurfaceBox>
      </div>

      <!-- 分组标签：实时日志 / 配置管理 -->
      <ConsoleSegmentedTabs
        v-model="activeTab"
        :options="[
          { value: 'logs', label: `实时日志 (${logs.length})` },
          { value: 'config', label: '任务与邮箱配置' }
        ]"
        aria-label="功能分区"
      />

      <!-- Tab 1: 实时日志 -->
      <div v-show="activeTab === 'logs'" class="space-y-3">
        <div class="flex items-center justify-between text-xs text-muted-foreground">
          <p>日志实时流式推送（展示最近 80 条记录，自动滚动）。</p>
          <div class="flex items-center gap-2">
            <span class="inline-block h-2 w-2 rounded-full bg-emerald-500"></span>
            <span>SSE 连接就绪</span>
          </div>
        </div>

        <div
          ref="logContainerRef"
          class="h-[28rem] overflow-y-auto rounded-xl border border-border bg-stone-950 p-4 font-mono text-xs leading-5 text-stone-200 select-text"
        >
          <div v-if="logs.length === 0" class="flex h-full items-center justify-center text-stone-500">
            暂无日志记录，点击上方“启动 Roxy”开始注册。
          </div>
          <div
            v-for="(item, idx) in logs"
            :key="idx"
            class="flex items-start gap-3 border-b border-stone-900/60 py-1 last:border-none"
          >
            <span class="shrink-0 text-stone-500 select-none">{{ item.time || '-' }}</span>
            <span class="break-all whitespace-pre-wrap" :class="getLogLevelClass(item.level)">
              {{ item.text }}
            </span>
          </div>
        </div>
      </div>

      <!-- Tab 2: 任务与邮箱配置 -->
      <div v-show="activeTab === 'config'" class="space-y-5">
        <FormSection title="调度与目标策略" density="roomy">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label class="block text-xs">
              <span class="ui-field-label">运行模式</span>
              <select
                v-model="localConfig.mode"
                class="ui-select-sm mt-1 w-full"
                :disabled="registerConfig?.enabled"
              >
                <option value="available">按健康账号数 (达标即停)</option>
                <option value="total">按注册总轮数 (跑完即停)</option>
                <option value="quota">按号池总配额 (达标即停)</option>
              </select>
            </label>

            <label class="block text-xs">
              <span class="ui-field-label">目标健康账号数</span>
              <Input
                v-model="targetAvailableInput"
                type="number"
                min="1"
                step="1"
                block
                :disabled="registerConfig?.enabled"
              />
            </label>

            <label class="block text-xs">
              <span class="ui-field-label">单轮注册任务数</span>
              <Input
                v-model="totalInput"
                type="number"
                min="1"
                step="1"
                block
                :disabled="registerConfig?.enabled"
              />
            </label>

            <label class="block text-xs">
              <span class="ui-field-label">并发线程数</span>
              <Input
                v-model="threadsInput"
                type="number"
                min="1"
                max="5"
                step="1"
                block
                :disabled="registerConfig?.enabled"
              />
            </label>
          </div>

          <div class="mt-4">
            <label class="block text-xs">
              <span class="ui-field-label">全局注册网络代理 (留空使用 Roxy 环境内置代理)</span>
              <Input
                v-model="localConfig.proxy"
                block
                root-class="font-mono"
                placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
                :disabled="registerConfig?.enabled"
              />
            </label>
          </div>
        </FormSection>

        <!-- 邮箱 Provider 列表 -->
        <FormSection title="邮箱服务提供商配置 (支持多 DDG 账号严格轮询)" density="roomy">
          <div class="space-y-3">
            <div
              v-for="(provider, pIdx) in localConfig.mail.providers"
              :key="pIdx"
              class="rounded-xl border border-border bg-card/60 p-4 transition-all"
            >
              <!-- 头部：折叠/展开 + 类型摘要 + 开关 + 删除 -->
              <div class="flex items-center justify-between gap-3">
                <button
                  type="button"
                  class="flex min-w-0 flex-1 items-center gap-2.5 text-left text-xs font-semibold text-foreground hover:opacity-80"
                  @click="toggleProviderCollapse(pIdx)"
                >
                  <span class="text-muted-foreground">
                    {{ isProviderExpanded(pIdx) ? '▼' : '▶' }}
                  </span>
                  <span class="font-mono text-sm">
                    {{ provider.type || '未命名' }}
                    <span v-if="provider.type === 'ddg_mail'" class="ml-2 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-600">
                      DDG #{{ pIdx + 1 }}
                    </span>
                  </span>
                  <span v-if="!isProviderExpanded(pIdx) && provider.api_base" class="text-muted-foreground font-mono text-[11px] truncate">
                    ({{ provider.api_base }})
                  </span>
                </button>

                <div class="flex items-center gap-3">
                  <label class="flex items-center gap-1.5 text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      v-model="provider.enable"
                      class="rounded border-border"
                      :disabled="registerConfig?.enabled"
                    />
                    <span>启用</span>
                  </label>
                  <Button
                    size="xs"
                    variant="ghost"
                    root-class="text-rose-600 hover:bg-rose-50"
                    :disabled="registerConfig?.enabled || localConfig.mail.providers.length <= 1"
                    @click="removeProvider(pIdx)"
                  >
                    删除
                  </Button>
                </div>
              </div>

              <!-- 展开的详细配置字段 -->
              <div v-show="isProviderExpanded(pIdx)" class="mt-4 space-y-4 border-t border-border pt-4">
                <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label class="block text-xs">
                    <span class="ui-field-label">提供商类型</span>
                    <select
                      v-model="provider.type"
                      class="ui-select-sm mt-1 w-full"
                      :disabled="registerConfig?.enabled"
                    >
                      <option value="ddg_mail">ddg_mail (DuckDuckGo 邮箱 + CF 中转)</option>
                      <option value="cloudflare_temp_email">cloudflare_temp_email (CF 临时邮箱)</option>
                      <option value="tempmail_lol">tempmail_lol (TempMail.lol)</option>
                      <option value="outlook_token">outlook_token (Outlook 邮箱池)</option>
                    </select>
                  </label>

                  <label class="block text-xs">
                    <span class="ui-field-label">中转 API 地址</span>
                    <Input
                      v-model="provider.api_base"
                      block
                      placeholder="https://your-temp-email-api.example.com"
                      :disabled="registerConfig?.enabled"
                    />
                  </label>
                </div>

                <!-- DDG 专属配置 -->
                <div v-if="provider.type === 'ddg_mail'" class="space-y-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs">
                  <p class="font-medium text-emerald-600">DuckDuckGo 凭证配置</p>
                  <label class="block text-xs">
                    <span class="ui-field-label">DDG Bearer Token</span>
                    <Input
                      v-model="provider.ddg_token"
                      block
                      type="password"
                      placeholder="从 duckduckgo.com 请求中抓取的 Bearer 令牌"
                      :disabled="registerConfig?.enabled"
                    />
                  </label>

                  <label class="block text-xs">
                    <span class="ui-field-label">CF Inbox JWT (固定收件箱 JWT)</span>
                    <Input
                      v-model="provider.cf_inbox_jwt"
                      block
                      type="password"
                      placeholder="中转服务生成的 CF 收件箱 JWT"
                      :disabled="registerConfig?.enabled"
                    />
                  </label>
                </div>

                <!-- 通用管理员凭证 -->
                <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label class="block text-xs">
                    <span class="ui-field-label">Admin Email (可选)</span>
                    <Input
                      v-model="provider.admin_email"
                      block
                      placeholder="管理员邮箱"
                      :disabled="registerConfig?.enabled"
                    />
                  </label>

                  <label class="block text-xs">
                    <span class="ui-field-label">Admin Password (可选)</span>
                    <Input
                      v-model="provider.admin_password"
                      block
                      type="password"
                      placeholder="管理员密码"
                      :disabled="registerConfig?.enabled"
                    />
                  </label>
                </div>
              </div>
            </div>

            <!-- 添加 Provider 按钮 -->
            <Button
              size="sm"
              variant="outline"
              class="w-full border-dashed"
              :disabled="registerConfig?.enabled"
              @click="addProvider"
            >
              + 添加一组 DDG / 邮箱配置
            </Button>
          </div>
        </FormSection>

        <!-- 保存按钮 -->
        <div class="flex justify-end pt-3">
          <Button
            size="sm"
            variant="primary"
            :disabled="registerConfig?.enabled || savingConfig"
            @click="handleSaveConfig"
          >
            {{ savingConfig ? '正在保存...' : '保存注册配置' }}
          </Button>
        </div>
      </div>
    </PagePanel>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Button, Input } from 'nanocat-ui'
import SurfaceBox from '@/components/ai/SurfaceBox.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import FormSection from '@/components/ai/FormSection.vue'
import ConsoleSegmentedTabs from '@/components/ai/ConsoleSegmentedTabs.vue'
import {
  fetchRoxyRegisterConfig,
  startRoxyRegister,
  stopRoxyRegister,
  resetRoxyRegister,
  saveSharedRegisterConfig,
  subscribeRoxyRegisterEvents,
  type RegisterConfig,
  type RegisterLogItem,
  type MailProviderConfig,
} from '@/api/register'

const activeTab = ref<'logs' | 'config'>('logs')
const loading = ref(false)
const actionLoading = ref(false)
const savingConfig = ref(false)
const registerConfig = ref<RegisterConfig | null>(null)
const logContainerRef = ref<HTMLDivElement | null>(null)
const expandedProviderIndices = ref<number[]>([0])

// 响应式表单字段
const targetAvailableInput = ref('10')
const totalInput = ref('10')
const threadsInput = ref('1')
const localConfig = ref<RegisterConfig>({
  mail: {
    request_timeout: 30,
    wait_timeout: 60,
    wait_interval: 2,
    api_use_register_proxy: true,
    providers: [],
  },
  proxy: '',
  total: 10,
  threads: 1,
  mode: 'available',
  target_quota: 250,
  target_available: 10,
  check_interval: 5,
  schedule_enabled: false,
  schedule_start: '08:00',
  schedule_end: '23:00',
  enabled: false,
})

let unsubscribeEvents: (() => void) | null = null

const stats = computed(() => {
  return registerConfig.value?.stats || {
    success: 0,
    fail: 0,
    done: 0,
    running: 0,
    threads: 1,
    elapsed_seconds: 0,
    avg_seconds: 0,
  }
})

const logs = computed<RegisterLogItem[]>(() => {
  return registerConfig.value?.logs || []
})

const successRate = computed(() => {
  const done = stats.value.done || 0
  const success = stats.value.success || 0
  if (!done) return 0
  return Math.round((success / done) * 100)
})

function getLogLevelClass(level: string) {
  if (level === 'red' || level === 'error') return 'text-rose-400'
  if (level === 'green' || level === 'success') return 'text-emerald-400'
  if (level === 'yellow' || level === 'warning') return 'text-amber-300'
  return 'text-stone-300'
}

function isProviderExpanded(idx: number) {
  return expandedProviderIndices.value.includes(idx)
}

function toggleProviderCollapse(idx: number) {
  if (expandedProviderIndices.value.includes(idx)) {
    expandedProviderIndices.value = expandedProviderIndices.value.filter(i => i !== idx)
  } else {
    expandedProviderIndices.value.push(idx)
  }
}

function addProvider() {
  localConfig.value.mail.providers.push({
    enable: true,
    type: 'ddg_mail',
    api_base: 'https://your-temp-email-api.example.com',
    admin_email: '',
    admin_password: '',
    ddg_token: '',
    cf_inbox_jwt: '',
  })
  expandedProviderIndices.value.push(localConfig.value.mail.providers.length - 1)
}

function removeProvider(idx: number) {
  if (localConfig.value.mail.providers.length <= 1) return
  localConfig.value.mail.providers.splice(idx, 1)
}

function syncFormFromConfig(cfg: RegisterConfig) {
  registerConfig.value = cfg
  localConfig.value = JSON.parse(JSON.stringify(cfg))
  targetAvailableInput.value = String(cfg.target_available || 10)
  totalInput.value = String(cfg.total || 10)
  threadsInput.value = String(cfg.threads || 1)
}

async function loadData() {
  loading.value = true
  try {
    const data = await fetchRoxyRegisterConfig()
    syncFormFromConfig(data.register)
  } catch (err) {
    console.error('加载 Roxy 配置失败', err)
  } finally {
    loading.value = false
  }
}

async function handleStart() {
  actionLoading.value = true
  try {
    const payload: Partial<RegisterConfig> = {
      mode: localConfig.value.mode,
      target_available: Math.max(1, Number(targetAvailableInput.value) || 1),
      total: Math.max(1, Number(totalInput.value) || 1),
      threads: Math.max(1, Number(threadsInput.value) || 1),
      proxy: (localConfig.value.proxy || '').trim(),
      mail: localConfig.value.mail,
    }
    const data = await startRoxyRegister(payload)
    syncFormFromConfig(data.register)
  } catch (err) {
    console.error('启动 Roxy 失败', err)
  } finally {
    actionLoading.value = false
  }
}

async function handleStop() {
  actionLoading.value = true
  try {
    const data = await stopRoxyRegister()
    syncFormFromConfig(data.register)
  } catch (err) {
    console.error('停止 Roxy 失败', err)
  } finally {
    actionLoading.value = false
  }
}

async function handleReset() {
  actionLoading.value = true
  try {
    const data = await resetRoxyRegister()
    syncFormFromConfig(data.register)
  } catch (err) {
    console.error('重置统计失败', err)
  } finally {
    actionLoading.value = false
  }
}

async function handleSaveConfig() {
  savingConfig.value = true
  try {
    const payload: Partial<RegisterConfig> = {
      mode: localConfig.value.mode,
      target_available: Math.max(1, Number(targetAvailableInput.value) || 1),
      total: Math.max(1, Number(totalInput.value) || 1),
      threads: Math.max(1, Number(threadsInput.value) || 1),
      proxy: (localConfig.value.proxy || '').trim(),
      mail: localConfig.value.mail,
    }
    const data = await saveSharedRegisterConfig(payload)
    syncFormFromConfig(data.register)
  } catch (err) {
    console.error('保存注册配置失败', err)
  } finally {
    savingConfig.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (logContainerRef.value) {
      logContainerRef.value.scrollTop = logContainerRef.value.scrollHeight
    }
  })
}

onMounted(() => {
  loadData()
  unsubscribeEvents = subscribeRoxyRegisterEvents((cfg) => {
    registerConfig.value = cfg
    scrollToBottom()
  })
})

onUnmounted(() => {
  if (unsubscribeEvents) {
    unsubscribeEvents()
    unsubscribeEvents = null
  }
})
</script>
