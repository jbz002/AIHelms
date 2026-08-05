<script setup lang="ts">
import type { SkillVersion } from '@aihelms/shared'

defineProps<{ version: SkillVersion | null }>()
</script>

<template>
  <span v-if="version" class="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-500">v{{ version.version }}</span>
</template>
