<script setup lang="ts">
import { TooltipRoot } from "reka-ui"
import { onMounted, onUnmounted, ref } from "vue"

const open = ref(false)

function onCloseOnScroll() {
  if (open.value) open.value = false
}

onMounted(() => {
  document.addEventListener("scroll", onCloseOnScroll, { capture: true, passive: true })
})
onUnmounted(() => {
  document.removeEventListener("scroll", onCloseOnScroll, { capture: true, passive: true })
})
</script>

<template>
  <TooltipRoot v-model:open="open">
    <slot />
  </TooltipRoot>
</template>
