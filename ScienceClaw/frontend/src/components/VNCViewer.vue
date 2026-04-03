<template>
  <iframe
    v-if="enabled && iframeSrc"
    :src="iframeSrc"
    class="vnc-frame"
    frameborder="0"
    scrolling="no"
    @load="handleLoad"
    @error="handleError"
  />
</template>

<script setup lang="ts">
import { computed, watch } from 'vue';

const props = defineProps<{
  sessionId: string;
  enabled?: boolean;
  viewOnly?: boolean;
  directWsUrl?: string;
}>();

const emit = defineEmits<{
  connected: [];
  disconnected: [reason?: any];
  credentialsRequired: [];
}>();

function buildIframeSrc(): string {
  const viewOnlyParam = props.viewOnly ? 'true' : 'false';

  if (props.directWsUrl) {
    const wsUrl = new URL(props.directWsUrl, window.location.origin);
    const params = new URLSearchParams({
      autoconnect: 'true',
      resize: 'scale',
      view_only: viewOnlyParam,
      path: wsUrl.pathname.replace(/^\/+/, ''),
    });
    return `/vnc/vnc_lite.html?${params.toString()}`;
  }

  const params = new URLSearchParams({
    autoconnect: 'true',
    resize: 'scale',
    view_only: viewOnlyParam,
    path: `api/v1/runtime/session/${props.sessionId}/http/websockify`,
  });
  return `/api/v1/runtime/session/${props.sessionId}/http/vnc/vnc_lite.html?${params.toString()}`;
}

const iframeSrc = computed(() => {
  if (!props.enabled || !props.sessionId) return '';
  return buildIframeSrc();
});

const handleLoad = () => {
  emit('connected');
};

const handleError = (event: Event) => {
  emit('disconnected', event);
};

watch(
  () => props.enabled,
  (enabled, prev) => {
    if (prev && !enabled) {
      emit('disconnected');
    }
  }
);
</script>

<style scoped>
.vnc-frame {
  display: block;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: rgb(40, 40, 40);
  border: 0;
}
</style>
