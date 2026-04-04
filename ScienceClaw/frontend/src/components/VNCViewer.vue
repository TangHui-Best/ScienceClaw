<template>
  <div
    ref="vncContainer"
    class="vnc-container"
    style="display: flex; width: 100%; height: 100%; overflow: auto; background: rgb(40, 40, 40);">
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount, watch } from 'vue';
import { getBackendWsUrl } from '@/utils/sandbox';
// @ts-ignore
import RFB from '@novnc/novnc/lib/rfb';

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

const vncContainer = ref<HTMLDivElement | null>(null);
let rfb: RFB | null = null;

const initVNCConnection = async () => {
  if (!vncContainer.value || !props.enabled) return;

  if (rfb) {
    rfb.disconnect();
    rfb = null;
  }

  try {
    const wsUrl = props.directWsUrl
      ? props.directWsUrl
      : getBackendWsUrl(`/rpa/vnc/${encodeURIComponent(props.sessionId)}`);

    rfb = new RFB(vncContainer.value, wsUrl, {
      credentials: { password: '' },
      shared: true,
      repeaterID: '',
      wsProtocols: ['binary'],
      scaleViewport: true,
    });

    rfb.viewOnly = props.viewOnly ?? false;
    rfb.scaleViewport = true;

    rfb.addEventListener('connect', () => {
      emit('connected');
    });

    rfb.addEventListener('disconnect', (e: any) => {
      emit('disconnected', e);
    });

    rfb.addEventListener('credentialsrequired', () => {
      emit('credentialsRequired');
    });
  } catch (error) {
    console.error('Failed to initialize VNC connection:', error);
  }
};

const disconnect = () => {
  if (rfb) {
    rfb.disconnect();
    rfb = null;
  }
};

watch([() => props.sessionId, () => props.enabled], () => {
  if (props.enabled && vncContainer.value) {
    initVNCConnection();
  } else {
    disconnect();
  }
}, { immediate: true });

watch(vncContainer, () => {
  if (vncContainer.value && props.enabled) {
    initVNCConnection();
  }
});

onBeforeUnmount(() => {
  disconnect();
});

defineExpose({
  disconnect,
  initConnection: initVNCConnection
});
</script>

<style scoped>
</style>
