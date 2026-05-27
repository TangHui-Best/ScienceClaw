<script setup lang="ts">
import { TooltipRoot } from "reka-ui"
</script>

<template>
  <TooltipRoot v-bind="$attrs">
    <slot />
  </TooltipRoot>
</template>
