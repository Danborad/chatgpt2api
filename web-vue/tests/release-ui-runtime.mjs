import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, ref } from 'vue'
import { createServer } from 'vite'

const server = await createServer({
  appType: 'custom',
  logLevel: 'silent',
  server: { middlewareMode: true },
})

function deferred() {
  let resolve
  const promise = new Promise(resolvePromise => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function createLifecycleRuntime() {
  const callbacks = {
    activate: [],
    deactivate: [],
    hide: [],
    show: [],
  }
  const isActive = ref(true)
  const isVisible = ref(true)
  const requestSeq = new Map()
  return {
    runtime: {
      isActive,
      isVisible,
      canRun: computed(() => isActive.value && isVisible.value),
      onActivate: callback => callbacks.activate.push(callback),
      onDeactivate: callback => callbacks.deactivate.push(callback),
      onHide: callback => callbacks.hide.push(callback),
      onShow: callback => callbacks.show.push(callback),
      setTimer: (_key, _delay, callback) => callback(),
      clearTimer: () => {},
      nextRequest: key => {
        const next = (requestSeq.get(key) || 0) + 1
        requestSeq.set(key, next)
        return next
      },
      invalidateRequest: key => {
        requestSeq.set(key, (requestSeq.get(key) || 0) + 1)
      },
      isLatestRequest: (key, seq, options = {}) => (
        isActive.value
        && (options.requireVisible === false || isVisible.value)
        && requestSeq.get(key) === seq
      ),
    },
    emit(name, context = { initial: false, visible: isVisible.value }) {
      callbacks[name].forEach(callback => callback(context))
    },
  }
}

try {
  const { parseChangelog, parseReleaseNotes } = await server.ssrLoadModule('/src/lib/release.ts')
  const changelogSource = await readFile(new URL('../../CHANGELOG.md', import.meta.url), 'utf8')
  const localReleases = parseChangelog(changelogSource)
  assert.equal(localReleases[0]?.version, 'Unreleased')
  assert.equal(localReleases[1]?.version, '3.0.0')
  assert.ok(localReleases[0]?.items.length > 0, 'the root changelog must remain renderable in the update dialog')
  const remoteReleases = parseReleaseNotes(
    'v3.0.1',
    '2026-08-07T00:00:00Z',
    '## 变更内容\n\n+ [新增] 页面在线更新。\n继续展示后端进度。\n+ [修复] 手动检查绕过缓存。',
  )
  assert.equal(remoteReleases[0]?.version, 'v3.0.1')
  assert.equal(remoteReleases[0]?.date, '2026-08-07')
  assert.equal(remoteReleases[0]?.items[0]?.content, '页面在线更新。 继续展示后端进度。')

  const { parseUpdateTaskResponse, parseVersionCheckResponse } = await server.ssrLoadModule('/src/api/version.ts')
  const updateProjection = parseVersionCheckResponse({
    current_tag: 'v3.0.0',
    latest_tag: 'v3.0.1',
    update_available: true,
    release_url: 'https://github.com/yukkcat/chatgpt2api/releases/tag/v3.0.1',
    status_label: '可更新',
    status_message: '发现新版本 v3.0.1。',
    tone: 'success',
    release_notes: '+ [新增] 页面在线更新。',
    release_published_at: '2026-08-07T00:00:00Z',
    can_update: true,
  })
  assert.equal(updateProjection.update_available, true)
  assert.equal(updateProjection.can_update, true)
  assert.throws(
    () => parseVersionCheckResponse({ ...updateProjection, tone: 'unknown' }),
    /response contract mismatch at response\.tone/,
  )
  const updateTask = parseUpdateTaskResponse({
    task_id: 'task-1',
    state: 'running',
    stage: 'downloading',
    current: 2,
    total: 6,
    status_label: '下载更新',
    message: '正在下载更新包。',
    busy: true,
    tone: 'info',
    error: '',
    current_tag: 'v3.0.0',
    latest_tag: 'v3.0.1',
    updated_at: '2026-08-07T00:00:00Z',
    events: [{
      id: 'event-1',
      timestamp: '2026-08-07T00:00:00Z',
      label: '下载更新',
      message: '正在下载更新包。',
      tone: 'info',
    }],
  })
  assert.equal(updateTask.state, 'running')
  assert.equal(updateTask.events[0]?.id, 'event-1')

  const [appShellSource, versionApiSource, accountsSource, logsTableSource, proxySource, monitorSource, monitorDetailRuntimeSource, monitorDetailSource, logsDetailSource, requestDetailDrawerSource, requestDetailSummarySource, requestDetailFieldsSource, requestDetailTimelineSource, slowCardSource, gallerySource, pageLoadingSource, userKeysPanelSource, listPaginationSource, listLayoutControlSource, accountActionButtonsSource, accountActionMenuSource, dashboardSource, dashboardPageSource] = await Promise.all([
    readFile(new URL('../src/layouts/AppShell.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/api/version.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/Accounts.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/logs/LogsSystemTable.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/Proxy.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/Monitor.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/monitor/monitorDetailRuntime.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/monitor/MonitorDetailDrawer.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/logs/LogsDetailDrawer.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/ai/RequestDetailDrawer.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/logs/RequestDetailSummary.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/logs/RequestDetailFields.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/logs/RequestDetailTimeline.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/monitor/MonitorSlowCard.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/Gallery.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/ai/PageLoadingState.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/settings/SettingsUserKeysPanel.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/ai/ListPagination.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/ai/ListLayoutControl.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/ai/AccountActionButtons.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/accounts/accountActionMenuRuntime.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/Dashboard.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/dashboard/useDashboardPage.ts', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(appShellSource, /raw\.githubusercontent\.com|fetchRemoteText|isNewerVersion/)
  assert.match(versionApiSource, /api\/system\/update-status/)
  assert.match(versionApiSource, /params: force \? \{ force: true \}/)
  assert.match(versionApiSource, /api\/system\/update/)
  assert.match(versionApiSource, /api\/system\/update-task/)
  assert.doesNotMatch(versionApiSource, /api\/system\/restart/)
  assert.match(appShellSource, /updateStatus\.value = result/)
  assert.match(appShellSource, /result\.status_message/)
  assert.doesNotMatch(appShellSource, /updateDeployment|当前部署|部署文档/)
  assert.doesNotMatch(appShellSource, /CHANGELOG\.md\?raw|localChangelog/)
  assert.match(appShellSource, /parseReleaseNotes/)
  assert.match(appShellSource, /立即更新/)
  assert.match(appShellSource, /@click="startUpdate"/)
  assert.match(appShellSource, /<OperationProgressDrawer/)
  assert.match(appShellSource, /releaseEntries\.value = remoteEntries/)
  assert.doesNotMatch(appShellSource, /versionApi\.restart|performUpdate/)
  assert.equal(appShellSource.includes('import.meta.env.DEV'), false)
  assert.match(appShellSource, /const headerServiceItems: HeaderServiceItem\[\] = \[/)
  assert.equal((appShellSource.match(/class="flex items-center gap-\[8px\]"/g) || []).length, 2)
  assert.match(appShellSource, /class="ml-auto flex shrink-0 items-center gap-\[12px\]"/)
  assert.match(appShellSource, /isImmersivePage \? 'p-0' : 'px-4 py-6 sm:px-6'/)
  assert.match(appShellSource, /<Tooltip :text="themeButtonTitle" placement="bottom">/)
  assert.match(appShellSource, /<Tooltip text="打开无限画布" placement="bottom">/)
  assert.match(appShellSource, /<Tooltip text="刷新当前页面" placement="bottom">/)
  assert.match(appShellSource, /<Tooltip text="查看接口信息" placement="bottom">/)
  assert.match(appShellSource, /<Tooltip text="交流与服务" placement="bottom">/)
  assert.match(appShellSource, /<Tooltip :text="`查看版本更新，当前 \$\{currentVersionLabel \|\| '版本未知'\}`" placement="bottom">/)
  assert.match(appShellSource, /aria-label="查看接口信息"[\s\S]*?接口[\s\S]*?aria-label="交流与服务"[\s\S]*?服务/)
  assert.doesNotMatch(appShellSource, /<Icon icon="lucide:circle-help"/)
  assert.doesNotMatch(appShellSource, /完整接口|apiFullUrl|\/v1\/chat\/completions/)
  assert.match(appShellSource, /items\.push\(\{ key: 'services', label: '交流与服务', dividerBefore: items\.length > 0 \}\)/)
  assert.match(appShellSource, /if \(key === 'services'\) \{\s*isServiceDialogOpen\.value = true/)
  assert.match(appShellSource, /max-width="min\(22rem, calc\(100vw - 24px\)\)"/)
  assert.match(appShellSource, /panel-class="w-full p-5"/)
  assert.equal((appShellSource.match(/https:\/\/qm\.qq\.com\/q\/yegwCqJisS/g) || []).length, 1)
  assert.equal((appShellSource.match(/https:\/\/pay\.ldxp\.cn\/shop\/yukkcat/g) || []).length, 1)
  assert.equal((appShellSource.match(/https:\/\/api\.klong\.lat/g) || []).length, 1)
  assert.match(appShellSource, /rel="noopener noreferrer"/)
  assert.match(appShellSource, /<main[\s\S]*?class="[^"]*bg-card[^"]*"/)
  assert.match(appShellSource, /const isContainedManagementPage = computed\(\(\) => isManagementPage\.value && isWorkspaceLayout\.value\)/)
  assert.match(appShellSource, /\{ 'lg:flex lg:h-dvh lg:min-h-0 lg:flex-col lg:overflow-hidden': isContainedManagementPage \}/)
  assert.equal((appShellSource.match(/isContainedManagementPage \? 'lg:flex lg:min-h-0 lg:flex-1 lg:flex-col/g) || []).length, 2)
  assert.equal(appShellSource.includes('route-pending-bar'), false)
  assert.equal(appShellSource.includes('route-pending-pulse'), false)
  assert.match(appShellSource, /<Suspense[\s\S]*?<template #fallback>[\s\S]*?<PageLoadingState/)
  assert.equal(pageLoadingSource.includes('dashed'), false)
  const userKeysLoadingMarkup = userKeysPanelSource.match(/<PageLoadingState[\s\S]*?\/>/)?.[0] || ''
  assert.equal(userKeysLoadingMarkup.includes('dashed'), false)
  assert.equal(listPaginationSource.includes('>每页</span>'), false)
  assert.equal(listLayoutControlSource.includes('>列表布局</span>'), false)
  assert.equal(accountActionButtonsSource.includes('reset-state'), false)
  assert.equal(accountActionMenuSource.includes("key: 'reset'"), false)
  assert.match(accountsSource, /:scroll-mode="isWorkspaceLayout \? 'contained' : 'page'"/)
  assert.match(accountsSource, /\.accounts-card-results--contained\s*\{[\s\S]*?max-height:\s*min\(36rem, 60dvh\)/)
  assert.match(logsTableSource, /:scroll-mode="layoutMode === 'workspace' \? 'contained' : 'page'"/)
  assert.match(proxySource, /:scroll-mode="isWorkspaceLayout \? 'contained' : 'page'"/)
  assert.equal(proxySource.includes('scroll-class="lg:max-h-[min(36rem,65vh)]'), false)
  assert.match(monitorSource, /<ConsoleSegmentedTabs[\s\S]*?:options="detailPanelOptions"[\s\S]*?fit="content"/)
  assert.match(monitorSource, /class="grid gap-3 xl:grid-cols-2"/)
  assert.match(monitorSource, /class="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4"/)
  assert.match(monitorSource, /\.monitor-metric-cell\s*\{[\s\S]*?min-height:\s*4\.5rem;[\s\S]*?justify-content:\s*center/)
  assert.match(monitorSource, /class="monitor-page"[\s\S]*?:class="\{ 'monitor-page--ready': Boolean\(monitorData\) \}"/)
  assert.match(monitorSource, /<PagePanel class="monitor-overview-panel space-y-5">/)
  assert.match(monitorSource, /\.monitor-page\s*\{[\s\S]*?display:\s*grid;[\s\S]*?gap:\s*1\.5rem/)
  assert.equal(monitorSource.includes('--monitor-data-card-height'), false)
  assert.doesNotMatch(monitorSource, /\.monitor-metric-group\s*\{[^}]*\n\s*height:/)
  assert.match(monitorSource, /<PagePanel v-else-if="monitorData" flush class="monitor-detail-panel">/)
  assert.match(monitorSource, /@media \(min-width: 1024px\)[\s\S]*?\.monitor-page--ready\s*\{[\s\S]*?grid-auto-rows:\s*minmax\(0, 1fr\)/)
  assert.match(monitorSource, /\.monitor-page--ready > \.monitor-detail-panel\s*\{[\s\S]*?contain:\s*size/)
  assert.match(monitorSource, /@media \(max-width: 1023px\)[\s\S]*?\.monitor-detail-panel\s*\{[\s\S]*?height:\s*min\(36rem, 72dvh\)/)
  assert.match(monitorSource, /\.monitor-detail-section\s*\{[\s\S]*?flex:\s*1 1 auto/)
  assert.match(slowCardSource, /class="mt-3 grid auto-rows-fr grid-cols-2 gap-2 text-xs"/)
  assert.match(slowCardSource, /class="flex min-h-9 min-w-0 items-center/)
  assert.match(slowCardSource, /class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3"/)
  assert.match(monitorSource, /\{ value: 'active', label: '活跃请求', count: activeRows\.value\.length \}/)
  assert.match(monitorSource, /\{ value: 'recent', label: '最近完成', count: recentRows\.value\.length \}/)
  assert.match(monitorSource, /\{ value: 'slow', label: '慢请求', count: slowRows\.value\.length \}/)
  assert.equal(monitorSource.includes("value: 'events'"), false)
  assert.equal(monitorSource.includes('MonitorEventRow'), false)
  assert.match(monitorSource, /<MonitorDetailDrawer[\s\S]*?:record="detailRecord"/)
  assert.match(monitorSource, /@open-detail="openDetail"/)
  assert.match(monitorSource, /action:\s*\(\)\s*=>\s*refreshMonitor\(true, 'auto'\)/)
  assert.match(
    monitorSource,
    /async function refreshMonitor[\s\S]*?Promise\.all\(\[[\s\S]*?loadMonitor\(silent, source\)[\s\S]*?monitorDetail\.refreshIfRunning\(\)/,
  )
  assert.match(monitorDetailRuntimeSource, /detailRecord\.value\.status !== 'running'/)
  assert.match(monitorDetailRuntimeSource, /await loadDetail\(callId, false\)/)
  assert.match(
    monitorSource,
    /pageRuntime\.onDeactivate\(\(\) => \{[\s\S]*?deactivateMonitor\(\)[\s\S]*?closeDetail\(\)/,
    'leaving the kept-alive monitor page must close and invalidate request details',
  )
  for (const detailSource of [monitorDetailSource, logsDetailSource]) {
    assert.match(detailSource, /<RequestDetailDrawer/)
  }
  assert.match(logsDetailSource, /<RequestDetailSummary/)
  assert.match(logsDetailSource, /<RequestDetailFields/)
  assert.match(logsDetailSource, /<RequestDetailTimeline/)
  assert.match(requestDetailDrawerSource, /<DrawerShell/)
  assert.match(requestDetailDrawerSource, /<SideDock/)
  assert.match(requestDetailDrawerSource, /SideDock \} from 'nanocat-ui'/)
  assert.equal(requestDetailDrawerSource.includes('<Teleport'), false)
  assert.equal(requestDetailDrawerSource.includes('position: fixed'), false)
  assert.match(requestDetailDrawerSource, /:root-class="rootClass"/)
  assert.match(requestDetailDrawerSource, /:show-backdrop="!detached"/)
  assert.match(requestDetailDrawerSource, /icon="lucide:minus"/)
  assert.match(requestDetailDrawerSource, /open && minimizable && minimized/)
  assert.match(requestDetailSummarySource, /<StateBadge/)
  assert.match(requestDetailFieldsSource, /<DetailFieldCard/)
  assert.match(requestDetailTimelineSource, /<RequestTimelineBreakdown/)
  assert.match(monitorDetailSource, /max-width="clamp\(22rem, 30vw, 32rem\)"/)
  assert.match(monitorDetailSource, /root-class="monitor-call-detail-drawer"/)
  assert.match(monitorDetailSource, /\sdetached\s/)
  assert.doesNotMatch(monitorDetailSource, /\sminimizable\s/)
  assert.match(monitorDetailSource, /class="monitor-call-detail__summary"/)
  assert.match(monitorDetailSource, /class="monitor-call-detail__facts"/)
  assert.match(monitorDetailSource, /class="monitor-call-timeline"/)
  assert.match(monitorDetailSource, /props\.record\?\.events/)
  assert.match(logsDetailSource, /<LogsImageAttemptTimeline/)
  assert.match(logsDetailSource, /title="原始 detail JSON"/)
  assert.match(monitorSource, /\.monitor-detail-card-list\s*\{[\s\S]*?grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(slowCardSource, /hover:border-primary\/30/)
  assert.equal(slowCardSource.includes('hover:bg-muted/20'), false)
  assert.equal((monitorSource.match(/<TableShell\s+fill\s+scroll-mode="contained"\s+hover-rows\s+unframed\s+sticky-header/g) || []).length, 2)
  assert.match(accountsSource, /loading-title="正在加载账号"[\s\S]*?loading-description="读取账号列表、分组和分页状态。"/)
  assert.match(logsTableSource, /loading-title="正在加载日志"[\s\S]*?loading-description="正在获取最新日志数据。"/)
  assert.match(proxySource, /loading-title="正在加载代理"[\s\S]*?loading-description="读取代理组、节点和健康状态。"/)
  assert.match(monitorSource, /\.monitor-detail-card-list\s*\{[\s\S]*?flex:\s*1 1 auto;[\s\S]*?overflow-y:\s*auto/)
  assert.match(monitorSource, /class="monitor-detail-card-list scrollbar-slim px-4 pb-4"/)
  assert.equal(monitorSource.includes('monitor-detail-card-list scrollbar-slim space-y-2'), false)
  assert.match(accountsSource, /<TableShell[\s\S]*?:scroll-mode="isWorkspaceLayout \? 'contained' : 'page'"[\s\S]*?sticky-header/)
  assert.doesNotMatch(accountsSource, /<TableShell[\s\S]*?:scroll-mode="isWorkspaceLayout \? 'contained' : 'page'"[\s\S]*?hover-rows[\s\S]*?sticky-header/)
  assert.match(logsTableSource, /<TableShell[\s\S]*?:scroll-mode="layoutMode === 'workspace' \? 'contained' : 'page'"[\s\S]*?hover-rows\s+sticky-header/)
  assert.match(proxySource, /<TableShell\s+unframed\s+hover-rows\s+sticky-header/)
  assert.match(gallerySource, /max-height:\s*min\(36rem, 60dvh\)/)
  assert.equal((dashboardSource.match(/<TimeRangeTabs\s+v-model=/g) || []).length, 5)
  assert.equal(dashboardSource.includes('TableShell'), false)
  assert.match(dashboardSource, /<div ref="detailChartRef" class="h-\[28rem\] w-full"><\/div>/)
  for (const rangeState of [
    'modelTimeRange',
    'trendTimeRange',
    'successRateTimeRange',
    'responseTimeTimeRange',
    'detailTimeRange',
  ]) {
    assert.match(dashboardPageSource, new RegExp(`const ${rangeState} = ref<DashboardTimeRange>`))
  }
  assert.equal((dashboardPageSource.match(/bindChartRange\(/g) || []).length, 6)
  assert.match(dashboardPageSource, /function updateDetailChart\(/)
  assert.match(dashboardPageSource, /function updateDetailChart\([\s\S]*?grid:\s*\{[\s\S]*?xAxis:\s*\{[\s\S]*?yAxis:\s*\[/)

  const { buildDashboardTrendSeries } = await server.ssrLoadModule(
    '/src/views/dashboard/dashboardTrendSeries.ts',
  )
  const trendSeries = buildDashboardTrendSeries({
    successRequests: [8],
    finalFailedRequests: [2],
    switchCount: [1],
  }, (name, data, color, options) => ({ name, data, color, options }), {
    success: '#16a34a',
    failure: '#dc2626',
    switchAccount: '#7c3aed',
  })
  assert.deepEqual(trendSeries.map(series => series.name), ['成功', '失败', '切号'])
  assert.equal(trendSeries.length, 3)

  globalThis.window = {
    localStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    },
  }

  const { useAccountPageLifecycleRuntime } = await server.ssrLoadModule(
    '/src/views/accounts/accountPageLifecycleRuntime.ts',
  )
  const accountLifecycle = createLifecycleRuntime()
  const firstAccountLoad = deferred()
  let accountDataLoads = 0
  let accountGroupLoads = 0
  let accountInvalidations = 0
  useAccountPageLifecycleRuntime({
    runtime: accountLifecycle.runtime,
    viewMode: ref('list'),
    pageSize: ref(20),
    currentPage: ref(1),
    keyword: ref(''),
    statusFilter: ref('all'),
    groupFilter: ref('all'),
    pageSizeDefault: 20,
    pageSizeOptions: [20, 50],
    reloadTimerKey: 'accounts:reload',
    loadData: async () => {
      accountDataLoads += 1
      if (accountDataLoads === 1) await firstAccountLoad.promise
    },
    loadGroups: async () => {
      accountGroupLoads += 1
    },
    invalidateData: () => { accountInvalidations += 1 },
    invalidateGroups: () => { accountInvalidations += 1 },
    clearSelection: () => {},
    clearPageSelection: () => {},
    shouldSkipRefresh: () => false,
  })

  accountLifecycle.emit('activate', { initial: true, visible: true })
  await Promise.resolve()
  assert.equal(accountDataLoads, 1)
  accountLifecycle.runtime.isVisible.value = false
  accountLifecycle.emit('hide', { initial: false, visible: false })
  accountLifecycle.runtime.isVisible.value = true
  accountLifecycle.emit('show', { initial: false, visible: true })
  await Promise.resolve()
  assert.equal(accountInvalidations, 2)
  assert.equal(accountDataLoads, 2, 'show must reload even while the invalidated initial request is unsettled')
  assert.equal(accountGroupLoads, 2)
  firstAccountLoad.resolve()
  await Promise.resolve()

  const { useSettingsTabRuntime } = await server.ssrLoadModule(
    '/src/views/settings/settingsTabRuntime.ts',
  )
  const settingsLifecycle = createLifecycleRuntime()
  const externalSourcesLoaded = ref(false)
  let settingsLoads = 0
  let externalSourceLoads = 0
  useSettingsTabRuntime({
    runtime: settingsLifecycle.runtime,
    activeTab: ref('cpa'),
    reloadSettings: async () => { settingsLoads += 1 },
    shouldSkipActivateReload: () => false,
    tabLoaders: [{
      tabs: ['cpa', 'sub2api'],
      loaded: externalSourcesLoaded,
      load: async () => {
        externalSourceLoads += 1
        externalSourcesLoaded.value = true
      },
    }],
    invalidators: [() => { externalSourcesLoaded.value = false }],
  })

  settingsLifecycle.emit('activate', { initial: true, visible: true })
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(settingsLoads, 1)
  assert.equal(externalSourceLoads, 1)
  settingsLifecycle.runtime.isVisible.value = false
  settingsLifecycle.emit('hide', { initial: false, visible: false })
  settingsLifecycle.runtime.isVisible.value = true
  settingsLifecycle.emit('show', { initial: false, visible: true })
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(settingsLoads, 2, 'show must refresh settings after hide invalidated its requests')
  assert.equal(externalSourceLoads, 2, 'the visible lazy external-source tab must reload after show')

  const { accountImportsApi } = await server.ssrLoadModule('/src/api/accountImports.ts')
  const { useSettingsExternalSourcesRuntime } = await server.ssrLoadModule(
    '/src/views/settings/settingsExternalSourcesRuntime.ts',
  )
  const originalListCPAPools = accountImportsApi.listCPAPools
  const originalListSub2APIServers = accountImportsApi.listSub2APIServers
  const cpaRequest = deferred()
  const sub2apiRequest = deferred()
  accountImportsApi.listCPAPools = () => cpaRequest.promise
  accountImportsApi.listSub2APIServers = () => sub2apiRequest.promise
  try {
    const sourceLifecycle = createLifecycleRuntime()
    const sources = useSettingsExternalSourcesRuntime({
      runtime: sourceLifecycle.runtime,
      cpaRequestKey: 'settings:cpa',
      sub2apiRequestKey: 'settings:sub2api',
    })
    const staleLoad = sources.loadExternalSources()
    sources.invalidate()
    sourceLifecycle.runtime.isVisible.value = false
    cpaRequest.resolve({ pools: [{ id: 'stale-cpa' }] })
    sub2apiRequest.resolve({ servers: [{ id: 'stale-sub2api' }] })
    await staleLoad
    assert.equal(
      sources.externalSourcesLoaded.value,
      false,
      'an invalidated hidden load must not mark lazy external-source data as ready',
    )
  } finally {
    accountImportsApi.listCPAPools = originalListCPAPools
    accountImportsApi.listSub2APIServers = originalListSub2APIServers
  }
} finally {
  delete globalThis.window
  await server.close()
}
