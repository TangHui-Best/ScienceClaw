<script setup lang="ts">
import { TooltipProvider } from "reka-ui"
</script>

<template>
  <TooltipProvider v-bind="$attrs">
    <slot />
  </TooltipProvider>
</template>
