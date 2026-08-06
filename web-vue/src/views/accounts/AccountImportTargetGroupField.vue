<template>
  <label class="block text-xs">
    <span class="ui-field-label">目标分组</span>
    <GroupedSelectMenu
      :model-value="modelValue"
      :options="options"
      selected-indicator="none"
      aria-label="目标分组"
      block
      :disabled="disabled || loading"
      @update:model-value="$emit('update:modelValue', String($event))"
    />
  </label>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { GroupedSelectMenu } from 'nanocat-ui'

import type { AccountGroup } from '@/api/accounts'

const props = withDefaults(defineProps<{
  modelValue: string
  groups: AccountGroup[]
  disabled?: boolean
  loading?: boolean
}>(), {
  disabled: false,
  loading: false,
})

defineEmits<{
  'update:modelValue': [value: string]
}>()

const options = computed(() => [
  { label: '保留来源分组', value: '__preserve__' },
  { label: '未分组', value: '' },
  ...props.groups.map((group) => ({
    label: group.name || group.id,
    value: group.id,
  })),
])
</script>
