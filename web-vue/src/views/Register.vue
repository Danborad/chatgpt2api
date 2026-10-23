<template>
  <div class="space-y-6 pb-16">
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
              :class="registerStatusBadgeClass"
            >
              <span class="h-2 w-2 rounded-full" :class="registerStatusDotClass"></span>
              {{ registerStatusText }}
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

      <!-- 定时周期注册休眠提示 -->
      <div
        v-if="isPeriodicWaiting && stats.retry_at"
        class="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs text-amber-700 dark:text-amber-300 flex flex-wrap items-center justify-between gap-2"
      >
        <div class="flex items-center gap-2">
          <span class="inline-block h-2 w-2 rounded-full bg-amber-500"></span>
          <span><b>定时周期注册休眠中</b>：已完成第 {{ stats.periodic_round || 1 }} 轮注册，下一轮计划于 <b>{{ formatNextRunTime(stats.retry_at) }}</b> 自动启动。</span>
        </div>
        <span class="text-[11px] text-amber-600/80 dark:text-amber-400/80">无需人工操作，到达设定间隔后自动唤醒</span>
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
        <!-- 1. Roxy 指纹浏览器客户端连接配置 -->
        <FormSection title="Roxy 指纹浏览器连接配置 (本机客户端)" density="roomy">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label class="block text-xs">
              <span class="ui-field-label">Roxy 本机 API 地址</span>
              <Input
                v-model="localConfig.roxy.api_base"
                block
                root-class="font-mono"
                placeholder="http://127.0.0.1:50000"
                :disabled="registerConfig?.enabled"
              />
            </label>

            <label class="block text-xs sm:col-span-1 lg:col-span-3">
              <div class="flex items-center justify-between">
                <span class="ui-field-label">Roxy API 密钥 (Token)</span>
                <button
                  type="button"
                  class="text-[11px] text-muted-foreground hover:text-foreground"
                  @click="showRoxyToken = !showRoxyToken"
                >
                  {{ showRoxyToken ? '隐藏' : '显示' }}
                </button>
              </div>
              <div class="mt-1">
                <Input
                  v-model="localConfig.roxy.api_token"
                  :type="showRoxyToken ? 'text' : 'password'"
                  block
                  root-class="font-mono"
                  placeholder="在 Roxy 客户端 -> API & AI MCP 页面获取"
                  :disabled="registerConfig?.enabled"
                />
              </div>
            </label>

            <label class="block text-xs sm:col-span-1 lg:col-span-2">
              <span class="ui-field-label">Roxy 团队 / 工作区 ID (workspaceId)</span>
              <Input
                v-model="localConfig.roxy.workspace_id"
                block
                root-class="font-mono"
                placeholder="留空自动识别；若报错“没有该团队权限”请在此填入团队ID"
                :disabled="registerConfig?.enabled"
              />
            </label>

            <label class="block text-xs sm:col-span-1 lg:col-span-2">
              <span class="ui-field-label">Roxy 项目 ID (projectId，可选)</span>
              <Input
                v-model="localConfig.roxy.project_id"
                block
                root-class="font-mono"
                placeholder="可选，留空使用默认或自动识别"
                :disabled="registerConfig?.enabled"
              />
            </label>
          </div>

          <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 items-center">
            <label class="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                v-model="localConfig.roxy.open_headless"
                class="rounded border-border"
                :disabled="registerConfig?.enabled"
              />
              <span>无头静默运行 (Headless，不弹窗)</span>
            </label>

            <label class="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                v-model="localConfig.roxy.activate_account"
                class="rounded border-border"
                :disabled="registerConfig?.enabled"
              />
              <span>注册成功后自动发送首条消息激活</span>
            </label>

            <label class="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                v-model="localConfig.roxy.ignore_proxy_check"
                class="rounded border-border"
                :disabled="registerConfig?.enabled"
              />
              <span>忽略代理通道预检 (不强制检测代理)</span>
            </label>

            <label class="block text-xs">
              <span class="ui-field-label">验证码单次等待超时 (秒)</span>
              <Input
                v-model="otpWaitSecondsInput"
                type="number"
                min="10"
                max="300"
                step="5"
                block
                :disabled="registerConfig?.enabled"
              />
            </label>
          </div>

          <p class="mt-2 text-[11px] text-muted-foreground">
            提示：若 Roxy 提示“用户没有该团队权限”，请在上方填入拥有环境创建权限的团队 ID；填入下方“全局注册网络代理”将自动注入 Roxy 窗口与注册网络中。
          </p>
        </FormSection>

        <!-- 2. 调度与目标策略 -->
        <FormSection title="调度与目标策略" density="roomy">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label class="block text-xs">
              <span class="ui-field-label">运行模式</span>
              <select
                v-model="localConfig.mode"
                class="ui-select-sm mt-1 w-full"
                :disabled="registerConfig?.enabled"
              >
                <option value="periodic">定时周期注册 (每隔 X 小时注册 N 个)</option>
                <option value="total">按注册总轮数 (跑完即停)</option>
                <option value="available">按健康账号数 (达标即停)</option>
                <option value="quota">按号池总配额 (达标即停)</option>
              </select>
            </label>

            <!-- 定时周期注册模式配置 -->
            <template v-if="localConfig.mode === 'periodic'">
              <label class="block text-xs">
                <span class="ui-field-label">定时周期时间 (小时)</span>
                <Input
                  v-model="periodicIntervalInput"
                  type="number"
                  min="0.1"
                  step="0.5"
                  block
                  placeholder="例如 1 或 2"
                  :disabled="registerConfig?.enabled"
                />
              </label>

              <label class="block text-xs">
                <span class="ui-field-label">每轮自动注册数量</span>
                <Input
                  v-model="periodicCountInput"
                  type="number"
                  min="1"
                  step="1"
                  block
                  placeholder="例如 1 或 2"
                  :disabled="registerConfig?.enabled"
                />
              </label>
            </template>

            <!-- 其它模式配置 -->
            <template v-else-if="localConfig.mode === 'available'">
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
            </template>

            <template v-else-if="localConfig.mode === 'quota'">
              <label class="block text-xs">
                <span class="ui-field-label">目标号池总配额</span>
                <Input
                  v-model="targetQuotaInput"
                  type="number"
                  min="1"
                  step="10"
                  block
                  :disabled="registerConfig?.enabled"
                />
              </label>
            </template>

            <template v-else-if="localConfig.mode === 'total'">
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
            </template>

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
  saveRoxyRegisterConfig,
  saveSharedRegisterConfig,
  subscribeRoxyRegisterEvents,
  type RegisterConfig,
  type RegisterLogItem,
  type MailProviderConfig,
  type RoxyConfig,
} from '@/api/register'

const activeTab = ref<'logs' | 'config'>('logs')
const loading = ref(false)
const actionLoading = ref(false)
const savingConfig = ref(false)
const registerConfig = ref<RegisterConfig | null>(null)
const logContainerRef = ref<HTMLDivElement | null>(null)
const expandedProviderIndices = ref<number[]>([0])
const showRoxyToken = ref(false)
const otpWaitSecondsInput = ref('60')

// 响应式表单字段
const targetAvailableInput = ref('10')
const targetQuotaInput = ref('250')
const totalInput = ref('10')
const threadsInput = ref('1')
const periodicIntervalInput = ref('1')
const periodicCountInput = ref('1')
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
  mode: 'periodic',
  target_quota: 250,
  target_available: 10,
  periodic_interval_hours: 1.0,
  periodic_count: 1,
  check_interval: 5,
  schedule_enabled: false,
  schedule_start: '08:00',
  schedule_end: '23:00',
  enabled: false,
  roxy: {
    api_base: 'http://127.0.0.1:50000',
    api_token: '',
    workspace_id: '',
    project_id: '',
    open_headless: false,
    create_use_proxy_pool: false,
    proxy_pool: '',
    activate_account: true,
    otp_wait_seconds: 60,
    ignore_proxy_check: true,
  },
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

const isPeriodicWaiting = computed(() => {
  return Boolean(
    registerConfig.value?.enabled &&
    (stats.value.pause_reason === 'periodic_interval_wait' ||
      (localConfig.value.mode === 'periodic' && stats.value.retry_at && (stats.value.running || 0) === 0))
  )
})

const registerStatusText = computed(() => {
  if (!registerConfig.value?.enabled) return '已停止'
  if (isPeriodicWaiting.value) return '定时休眠中'
  return '运行中'
})

const registerStatusBadgeClass = computed(() => {
  if (!registerConfig.value?.enabled) return 'bg-muted text-muted-foreground'
  if (isPeriodicWaiting.value) return 'bg-amber-500/10 text-amber-600'
  return 'bg-emerald-500/10 text-emerald-600'
})

const registerStatusDotClass = computed(() => {
  if (!registerConfig.value?.enabled) return 'bg-stone-400'
  if (isPeriodicWaiting.value) return 'bg-amber-500'
  return 'bg-emerald-500 animate-pulse'
})

function formatNextRunTime(isoString?: string | null) {
  if (!isoString) return '-'
  try {
    const d = new Date(isoString)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(isoString)
  }
}

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
    api_base: '',
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
  targetQuotaInput.value = String(cfg.target_quota || 250)
  totalInput.value = String(cfg.total || 10)
  threadsInput.value = String(cfg.threads || 1)
  periodicIntervalInput.value = String(cfg.periodic_interval_hours || 1)
  periodicCountInput.value = String(cfg.periodic_count || 1)
  if (!localConfig.value.roxy) {
    localConfig.value.roxy = {
      api_base: 'http://127.0.0.1:50000',
      api_token: '',
      workspace_id: '',
      project_id: '',
      open_headless: false,
      create_use_proxy_pool: false,
      proxy_pool: '',
      activate_account: true,
      otp_wait_seconds: 60,
      ignore_proxy_check: true,
    }
  }
  otpWaitSecondsInput.value = String(localConfig.value.roxy?.otp_wait_seconds || 60)
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
    const roxyPayload: RoxyConfig = {
      api_base: (localConfig.value.roxy?.api_base || 'http://127.0.0.1:50000').trim(),
      api_token: (localConfig.value.roxy?.api_token || '').trim(),
      workspace_id: (localConfig.value.roxy?.workspace_id || '').trim(),
      project_id: (localConfig.value.roxy?.project_id || '').trim(),
      open_headless: Boolean(localConfig.value.roxy?.open_headless),
      create_use_proxy_pool: false,
      proxy_pool: '',
      activate_account: localConfig.value.roxy?.activate_account !== false,
      otp_wait_seconds: Math.max(10, Number(otpWaitSecondsInput.value) || 60),
      ignore_proxy_check: localConfig.value.roxy?.ignore_proxy_check !== false,
    }
    const payload: Partial<RegisterConfig> = {
      mode: localConfig.value.mode,
      target_available: Math.max(1, Number(targetAvailableInput.value) || 1),
      target_quota: Math.max(1, Number(targetQuotaInput.value) || 1),
      total: Math.max(1, Number(totalInput.value) || 1),
      threads: Math.max(1, Number(threadsInput.value) || 1),
      periodic_interval_hours: Math.max(0.1, Number(periodicIntervalInput.value) || 1.0),
      periodic_count: Math.max(1, Number(periodicCountInput.value) || 1),
      proxy: (localConfig.value.proxy || '').trim(),
      mail: localConfig.value.mail,
      roxy: roxyPayload,
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
    const roxyPayload: RoxyConfig = {
      api_base: (localConfig.value.roxy?.api_base || 'http://127.0.0.1:50000').trim(),
      api_token: (localConfig.value.roxy?.api_token || '').trim(),
      workspace_id: (localConfig.value.roxy?.workspace_id || '').trim(),
      project_id: (localConfig.value.roxy?.project_id || '').trim(),
      open_headless: Boolean(localConfig.value.roxy?.open_headless),
      create_use_proxy_pool: false,
      proxy_pool: '',
      activate_account: localConfig.value.roxy?.activate_account !== false,
      otp_wait_seconds: Math.max(10, Number(otpWaitSecondsInput.value) || 60),
      ignore_proxy_check: localConfig.value.roxy?.ignore_proxy_check !== false,
    }
    const payload: Partial<RegisterConfig> = {
      mode: localConfig.value.mode,
      target_available: Math.max(1, Number(targetAvailableInput.value) || 1),
      target_quota: Math.max(1, Number(targetQuotaInput.value) || 1),
      total: Math.max(1, Number(totalInput.value) || 1),
      threads: Math.max(1, Number(threadsInput.value) || 1),
      periodic_interval_hours: Math.max(0.1, Number(periodicIntervalInput.value) || 1.0),
      periodic_count: Math.max(1, Number(periodicCountInput.value) || 1),
      proxy: (localConfig.value.proxy || '').trim(),
      mail: localConfig.value.mail,
      roxy: roxyPayload,
    }
    const data = await saveRoxyRegisterConfig(payload)
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
