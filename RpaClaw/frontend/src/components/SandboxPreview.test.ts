// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock('@/api/client', () => ({ apiClient: { get: vi.fn().mockResolvedValue({ data: { data: { tabs: [] } } }), post: vi.fn() } }));
vi.mock('@/utils/sandbox', () => ({
  isLocalMode: () => true,
  getBackendWsUrl: () => 'ws://localhost/api/v1/noop',
  getBackendVncPageUrl: () => '',
}));
vi.mock('./SandboxTerminal.vue', () => ({ default: { template: '<div />' } }));

class FakeWebSocket {
  static OPEN = 1; static instances: FakeWebSocket[] = [];
  readyState = FakeWebSocket.OPEN; sent: string[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null; onclose: (() => void) | null = null;
  constructor(public url: string) { FakeWebSocket.instances.push(this); }
  send(value: string) { this.sent.push(value); }
  close() { this.readyState = 3; this.onclose?.(); }
}

describe('SandboxPreview interactive generic session screencast', () => {
  beforeEach(() => { FakeWebSocket.instances = []; vi.stubGlobal('WebSocket', FakeWebSocket); document.body.innerHTML = ''; });

  it('forwards mouse, wheel and keyboard through the generic sessions websocket', async () => {
    const { default: Preview } = await import('./SandboxPreview.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Preview, { mode: 'browser', isLive: true, sessionId: 'browser-host-1', variant: 'inline' }); app.mount(root); await nextTick(); await nextTick();
    const ws = FakeWebSocket.instances[0]; expect(String(ws.url)).toContain('/api/v1/sessions/browser-host-1/browser/screencast');
    const canvas = root.querySelector<HTMLCanvasElement>('canvas')!;
    Object.defineProperty(canvas, 'getBoundingClientRect', { value: () => ({ left: 0, top: 0, width: 100, height: 100 }) });
    canvas.dispatchEvent(new MouseEvent('mousedown', { clientX: 50, clientY: 50, button: 0, bubbles: true }));
    canvas.dispatchEvent(new WheelEvent('wheel', { clientX: 50, clientY: 50, deltaY: 12, bubbles: true }));
    canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', code: 'KeyA', bubbles: true }));
    expect(ws.sent.map((item) => JSON.parse(item).type)).toEqual(['mouse', 'wheel', 'keyboard']);
    expect(JSON.stringify(ws.sent)).not.toContain('/rpa/session');
    app.unmount();
  }, 15_000);

  it('uses the atomic manual producer instead of websocket defaults while recording', async () => {
    const dispatch = vi.fn().mockResolvedValue(undefined);
    const { default: Preview } = await import('./SandboxPreview.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Preview, {
      mode: 'browser', isLive: true, sessionId: 'browser-host-1', variant: 'inline',
      manualInputDispatcher: dispatch,
    });
    app.mount(root); await nextTick(); await nextTick();
    const ws = FakeWebSocket.instances[0];
    const canvas = root.querySelector<HTMLCanvasElement>('canvas')!;
    Object.defineProperty(canvas, 'getBoundingClientRect', { value: () => ({ left: 0, top: 0, width: 100, height: 100 }) });
    canvas.dispatchEvent(new MouseEvent('mousedown', { clientX: 25, clientY: 50, button: 0, bubbles: true }));
    canvas.dispatchEvent(new MouseEvent('mouseup', { clientX: 25, clientY: 50, button: 0, bubbles: true }));
    canvas.dispatchEvent(new KeyboardEvent('keydown', { key: '7', code: 'Digit7', bubbles: true }));
    const paste = new Event('paste', { bubbles: true }) as ClipboardEvent;
    Object.defineProperty(paste, 'clipboardData', { value: { getData: () => 'PO-2026-A' } });
    canvas.dispatchEvent(paste);
    await vi.waitFor(() => expect(dispatch).toHaveBeenCalledTimes(3));
    expect(dispatch.mock.calls.map(([value]) => value.kind)).toEqual(['click', 'text', 'paste']);
    expect(dispatch.mock.calls[0][0]).toMatchObject({ x: 75, y: 75 });
    expect(dispatch.mock.calls[0][0].input_id).toMatch(/^input_[a-z0-9_]+$/);
    expect(ws.sent).toEqual([]);
    app.unmount();
  }, 15_000);
});
