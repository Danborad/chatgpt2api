<template>
  <FormSection title="概览中心">
    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <FormField label="默认统计周期">
        <template #label-extra>
          <HelpTip text="新打开概览中心时，各图表默认使用这个统计周期；进入页面后仍可单独切换。" />
        </template>
        <GroupedSelectMenu
          :model-value="defaultTimeRange"
          :options="DASHBOARD_TIME_RANGE_OPTIONS"
          selected-indicator="none"
          aria-label="概览中心默认统计周期"
          block
          @update:model-value="setDefaultTimeRange"
        />
      </FormField>

      <FormField label="自动刷新间隔（秒）">
        <template #label-extra>
          <HelpTip text="默认 10 秒，可设置为 5–300 秒。修改后保存在当前浏览器，不写入后端业务配置。" />
        </template>
        <Input
          :model-value="refreshIntervalDraft"
          type="number"
          min="5"
          max="300"
          step="1"
          block
          @update:model-value="refreshIntervalDraft = $event"
          @blur="commitRefreshInterval"
          @keyup.enter="commitRefreshInterval"
        />
      </FormField>
    </div>
  </FormSection>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { FormField, FormSection, GroupedSelectMenu, HelpTip, Input } from 'nanocat-ui'
import { DASHBOARD_TIME_RANGE_OPTIONS } from '@/lib/timeRanges'
import {
  readDashboardDefaultTimeRange,
  readDashboardRefreshIntervalSeconds,
  writeDashboardDefaultTimeRange,
  writeDashboardRefreshIntervalSeconds,
} from '@/views/dashboard/dashboardPreferences'

const defaultTimeRange = ref(readDashboardDefaultTimeRange())
const refreshIntervalDraft = ref(String(readDashboardRefreshIntervalSeconds()))

function setDefaultTimeRange(value: string | string[]) {
  defaultTimeRange.value = writeDashboardDefaultTimeRange(value)
}

function commitRefreshInterval() {
  const seconds = writeDashboardRefreshIntervalSeconds(refreshIntervalDraft.value)
  refreshIntervalDraft.value = String(seconds)
}
</script>
